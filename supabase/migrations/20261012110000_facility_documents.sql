set search_path = public, extensions;

create table if not exists public.facility_documents (
    id text primary key,
    title text not null check (length(trim(title)) between 1 and 120),
    description text not null default '' check (length(description) <= 240),
    original_filename text,
    storage_path text,
    source_url text,
    created_at text not null,
    check (
        (storage_path is not null and source_url is null)
        or (storage_path is null and source_url is not null)
    )
);

alter table public.facility_documents enable row level security;
revoke all on public.facility_documents from anon, authenticated;
grant all on public.facility_documents to service_role;

insert into public.facility_documents
    (id, title, description, source_url, created_at)
values
    (
        'legacy-cytoflex-lx',
        'CytoFLEX LX',
        'PDF · listed as modified 5 November 2020',
        'https://drive.google.com/file/d/1-ngsJzFZl00ujRPjUp7CCU7XbvuuNn7g/view?usp=drive_web',
        now()::text
    ),
    (
        'legacy-user-charges',
        'Revised user charges',
        'PDF · posted 16 October 2023; effective 1 November 2023',
        'https://drive.google.com/file/d/1IypqLbMMFEdebMY9m-HYlPagSZt_hX5S/view?usp=drive_web',
        now()::text
    )
on conflict (id) do nothing;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'facility-documents',
    'facility-documents',
    false,
    10485760,
    array['application/pdf']
)
on conflict (id) do update
set public = false,
    file_size_limit = 10485760,
    allowed_mime_types = array['application/pdf'];
