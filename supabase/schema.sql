-- Run once in a NEW Supabase project using its SQL editor. Safe to run again.
-- No anonymous/authenticated browser access. Only the backend secret key can
-- call this RPC. All task and version queries include the visitor identifier.
begin;
create table if not exists public.brief_visitors (
  id text primary key check (id ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now()
);
create table if not exists public.brief_tasks (
  visitor text not null references public.brief_visitors(id),
  id text not null, payload jsonb not null, primary key(visitor,id)
);
create table if not exists public.brief_versions (
  visitor text not null, task_id text not null, id text not null,
  payload jsonb not null, primary key(visitor,id),
  foreign key(visitor,task_id) references public.brief_tasks(visitor,id)
);
create index if not exists brief_versions_task on public.brief_versions(visitor,task_id);
create table if not exists public.brief_files (
  visitor text not null references public.brief_visitors(id),
  object_key text primary key, bytes bigint not null check(bytes>=0),
  sha256 text not null, ready boolean not null default false
);
create table if not exists public.brief_counters (
  scope text not null, bucket text not null, n integer not null,
  primary key(scope,bucket)
);
create table if not exists public.brief_runtime (
  singleton boolean primary key default true check(singleton),
  owner text not null, expires_at timestamptz not null
);

alter table public.brief_visitors enable row level security;
alter table public.brief_tasks enable row level security;
alter table public.brief_versions enable row level security;
alter table public.brief_files enable row level security;
alter table public.brief_counters enable row level security;
alter table public.brief_runtime enable row level security;
revoke all on public.brief_visitors, public.brief_tasks, public.brief_versions,
  public.brief_files, public.brief_counters, public.brief_runtime from public, anon, authenticated;

insert into storage.buckets(id,name,public,file_size_limit)
values ('brief-private','brief-private',false,12000000)
on conflict(id) do update set public=false,file_size_limit=12000000;
-- Do not add public Storage policies. Downloads go through our visitor API.

create or replace function public.brief_cloud(op text, visitor text default '', owner_id text default '', body jsonb default '{}')
returns jsonb language plpgsql security definer set search_path='' as $$
declare
  result jsonb; item jsonb; old_value jsonb; new_versions jsonb;
  day_key text := to_char(now() at time zone 'UTC','YYYY-MM-DD');
  hour_key text := to_char(now() at time zone 'UTC','YYYY-MM-DD"T"HH24');
  object_name text; total_bytes bigint; visitor_bytes bigint; added_bytes bigint;
begin
  if op='ping' then
    if not exists(select 1 from storage.buckets where id='brief-private' and not public) then
      return jsonb_build_object('error','private_bucket_required','status',503);
    end if;
    return jsonb_build_object('schema',1);
  end if;
  -- Serializes limits, lease transfer, and task/version commits across replicas.
  perform pg_advisory_xact_lock(184320260920);
  if op='claim' then
    if length(owner_id)<32 then return jsonb_build_object('error','invalid_owner','status',400); end if;
    insert into public.brief_runtime(singleton,owner,expires_at)
    values (true,owner_id,now()+interval '75 seconds')
    on conflict(singleton) do update set owner=excluded.owner,expires_at=excluded.expires_at
    where public.brief_runtime.owner=owner_id or public.brief_runtime.expires_at<now();
    return jsonb_build_object('owned',exists(select 1 from public.brief_runtime where owner=owner_id and expires_at>now()));
  end if;
  if op='renew' then
    update public.brief_runtime set expires_at=now()+interval '75 seconds'
    where owner=owner_id and expires_at>now();
    return jsonb_build_object('owned',found);
  end if;
  if op='release' then
    delete from public.brief_runtime where owner=owner_id;
    return '{}'::jsonb;
  end if;
  if op='visitor_exists' then
    return to_jsonb(exists(select 1 from public.brief_visitors v where v.id=visitor));
  end if;
  if op='visitor_new' then
    if exists(select 1 from public.brief_visitors v where v.id=visitor) then return '{}'::jsonb; end if;
    if (select count(*) from public.brief_visitors)>=coalesce((body->>'max_visitors')::int,200) then
      return jsonb_build_object('error','visitors_full','status',503);
    end if;
    if coalesce((select n from public.brief_counters where scope='visitors' and bucket=hour_key),0)>=30 then
      return jsonb_build_object('error','visitors_rate','status',429);
    end if;
    insert into public.brief_visitors(id) values(visitor);
    insert into public.brief_counters values('visitors',hour_key,1)
    on conflict(scope,bucket) do update set n=public.brief_counters.n+1;
    return '{}'::jsonb;
  end if;
  if not exists(select 1 from public.brief_visitors v where v.id=visitor) then
    return jsonb_build_object('error','visitor_missing','status',401);
  end if;
  if op='get' then
    select t.payload into result from public.brief_tasks t where t.visitor=brief_cloud.visitor and t.id=body->>'id';
    return result;
  elsif op='list' then
    return (select coalesce(jsonb_agg(t.payload),'[]') from public.brief_tasks t where t.visitor=brief_cloud.visitor);
  elsif op='versions' then
    return (select coalesce(jsonb_agg(v.payload),'[]') from public.brief_versions v where v.visitor=brief_cloud.visitor and v.task_id=body->>'id');
  end if;
  -- A stale deployment cannot write state or consume model quota after takeover.
  if not exists(select 1 from public.brief_runtime where owner=owner_id and expires_at>now()) then
    return jsonb_build_object('error','lease_lost','status',503);
  end if;
  if op='model_budget' then
    if coalesce((select n from public.brief_counters where scope='model:global' and bucket=day_key),0)>=(body->>'global_limit')::int then
      return jsonb_build_object('error','global_budget','status',429);
    end if;
    if coalesce((select n from public.brief_counters where scope='model:'||visitor and bucket=day_key),0)>=(body->>'visitor_limit')::int then
      return jsonb_build_object('error','visitor_budget','status',429);
    end if;
    insert into public.brief_counters values('model:global',day_key,1),('model:'||visitor,day_key,1)
    on conflict(scope,bucket) do update set n=public.brief_counters.n+1;
    delete from public.brief_counters where bucket<to_char(now()-interval '3 days','YYYY-MM-DD');
    return '{}'::jsonb;
  elsif op in ('storage_guard','reserve_file') then
    added_bytes:=coalesce((body->>'extra')::bigint,0);
    if op='reserve_file' then
      object_name:=body->>'key';
      if left(object_name,65)<>visitor||'/' or object_name like '%..%' then
        return jsonb_build_object('error','invalid_object','status',400);
      end if;
      select to_jsonb(f) into result from public.brief_files f where f.object_key=object_name;
      if result is not null then
        if result->>'sha256'<>body->>'sha256' then return jsonb_build_object('error','immutable_file','status',409); end if;
        return jsonb_build_object('ready',(result->>'ready')::boolean);
      end if;
      added_bytes:=(body->>'bytes')::bigint;
      if added_bytes<0 or added_bytes>12000000 then return jsonb_build_object('error','file_too_large','status',413); end if;
    end if;
    select coalesce(sum(f.bytes),0),coalesce(sum(f.bytes) filter(where f.visitor=brief_cloud.visitor),0)
    into total_bytes,visitor_bytes from public.brief_files f;
    if total_bytes+added_bytes>700000000 or visitor_bytes+added_bytes>50000000 then
      return jsonb_build_object('error','storage_full','status',413);
    end if;
    if op='reserve_file' then
      insert into public.brief_files(visitor,object_key,bytes,sha256) values(visitor,object_name,added_bytes,body->>'sha256');
    end if;
    return jsonb_build_object('ready',false);
  elsif op='file_ready' then
    update public.brief_files f set ready=true where f.visitor=brief_cloud.visitor and f.object_key=body->>'key';
    return '{}'::jsonb;
  elsif op='save' then
    item:=body->'task';
    if jsonb_typeof(item)<>'object' or coalesce(item->>'id','')!~'^[a-f0-9]{32}$' then
      return jsonb_build_object('error','invalid_task','status',400);
    end if;
    select t.payload into old_value from public.brief_tasks t where t.visitor=brief_cloud.visitor and t.id=item->>'id';
    if old_value is null and (select count(*) from public.brief_tasks t where t.visitor=brief_cloud.visitor)>=20 then
      return jsonb_build_object('error','tasks_full','status',429);
    end if;
    -- Incremental size accounting is computed from text bytes, conservatively
    -- leaving headroom below the free 500MB database quota for indexes and MVCC.
    select coalesce(sum(octet_length(t.payload::text)),0) into total_bytes from public.brief_tasks t;
    select total_bytes+coalesce(sum(octet_length(v.payload::text)),0) into total_bytes from public.brief_versions v;
    select coalesce(sum(octet_length(t.payload::text)),0) into visitor_bytes from public.brief_tasks t where t.visitor=brief_cloud.visitor;
    select visitor_bytes+coalesce(sum(octet_length(v.payload::text)),0) into visitor_bytes from public.brief_versions v where v.visitor=brief_cloud.visitor;
    -- An acknowledged commit may be lost in transit. Retrying the same version
    -- IDs must not use extra quota or fail at the version limit.
    select coalesce(jsonb_agg(v.value),'[]') into new_versions
    from jsonb_array_elements(coalesce(body->'versions','[]')) v
    where not exists(select 1 from public.brief_versions saved where saved.visitor=brief_cloud.visitor and saved.id=v.value->>'id');
    added_bytes:=octet_length(item::text)-coalesce(octet_length(old_value::text),0)+octet_length(new_versions::text);
    if total_bytes+added_bytes>200000000 or visitor_bytes+added_bytes>25000000 or octet_length(item::text)>6000000 then
      return jsonb_build_object('error','database_full','status',413);
    end if;
    if (select count(*) from public.brief_versions v where v.visitor=brief_cloud.visitor and v.task_id=item->>'id')+
       jsonb_array_length(new_versions)>80 then
      return jsonb_build_object('error','versions_full','status',429);
    end if;
    insert into public.brief_tasks(visitor,id,payload) values(visitor,item->>'id',item)
    on conflict on constraint brief_tasks_pkey do update set payload=excluded.payload;
    for result in select value from jsonb_array_elements(coalesce(body->'versions','[]')) loop
      if result->>'task_id'<>item->>'id' then raise exception 'invalid version task'; end if;
      insert into public.brief_versions(visitor,task_id,id,payload) values(visitor,item->>'id',result->>'id',result)
      on conflict on constraint brief_versions_pkey do nothing;
    end loop;
    return '{}'::jsonb;
  end if;
  return jsonb_build_object('error','unknown_operation','status',400);
end;
$$;
revoke all on function public.brief_cloud(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.brief_cloud(text,text,text,jsonb) to service_role;
notify pgrst, 'reload schema';
commit;
