create table if not exists public.app_records (
  collection text not null,
  record_id text not null,
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (collection, record_id),
  check (collection in ('employees', 'hotels', 'submissions', 'receipts', 'room_claims', 'settings'))
);

create index if not exists app_records_collection_idx
  on public.app_records (collection);

alter table public.app_records enable row level security;

insert into storage.buckets (id, name, public, file_size_limit)
values ('stay-files', 'stay-files', false, 10485760)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit;

-- แอป Streamlit เชื่อมจากฝั่ง server ด้วย service-role key ที่เก็บใน Secrets เท่านั้น
-- จงใจไม่สร้าง policy สำหรับ anon เพื่อป้องกันการอ่าน/เขียนจาก browser โดยตรง
