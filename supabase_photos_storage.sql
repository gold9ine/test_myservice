-- Supabase Storage photos 버킷: 화면(anon 키)에서 그림을 올리고, 올라온 목록을 볼 수 있게 허용한다
-- Supabase 대시보드 > SQL Editor 에 붙여 넣고 Run 을 누르세요. 여러 번 실행해도 오류가 나지 않습니다.
-- 고치기(덮어쓰기)·지우기는 열지 않습니다. 같은 이름으로 다시 올리면 막힙니다.

-- 1) 버킷: 없을 때만 만든다 (그림만, 한 장에 5MB 까지, 주소로 바로 볼 수 있게 공개)
--    이미 있는 photos 버킷은 설정을 바꾸지 않는다
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 5242880, array['image/png', 'image/jpeg', 'image/gif', 'image/webp'])
on conflict (id) do nothing;

-- 2) 허용: photos 버킷 안에서만 올리기(insert)와 목록 보기(select)
drop policy if exists "photos 올리기" on storage.objects;
create policy "photos 올리기" on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'photos');

drop policy if exists "photos 목록 보기" on storage.objects;
create policy "photos 목록 보기" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'photos');

-- 3) 확인: 아래 결과에 버킷 한 줄과 허용 두 줄(INSERT, SELECT)이 보이면 된다
select 'bucket' as 종류, id as 이름, case when public then '공개' else '비공개' end as 내용
from storage.buckets
where id = 'photos'
union all
select 'policy', policyname, cmd || ' / ' || array_to_string(roles, ', ')
from pg_policies
where schemaname = 'storage' and tablename = 'objects' and policyname like 'photos %';
