-- Supabase Storage docs 버킷: 화면(anon 키)에서 문서를 올리고, 올라온 목록을 볼 수 있게 허용한다
-- Supabase 대시보드 > SQL Editor 에 붙여 넣고 Run 을 누르세요. 여러 번 실행해도 오류가 나지 않습니다.
-- 고치기(덮어쓰기)·지우기는 열지 않습니다. 같은 이름으로 다시 올리면 막힙니다.

-- 1) 버킷: 없으면 만들고, 이미 있으면 받을 문서 종류와 크기 한도만 맞춘다
--    문서는 계약서처럼 남이 보면 안 되는 것이 많아 비공개로 만든다 (주소만 알아서는 못 열고, 키로 내려받는다)
--    이미 있는 버킷의 공개/비공개 설정은 바꾸지 않는다
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'docs', 'docs', false,
  20971520,  -- 한 개에 20MB 까지
  array[
    'application/pdf',                                                          -- PDF
    'application/msword',                                                       -- Word (doc)
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  -- Word (docx)
    'application/vnd.ms-excel',                                                 -- Excel (xls)
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',        -- Excel (xlsx)
    'application/vnd.ms-powerpoint',                                            -- PowerPoint (ppt)
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',-- PowerPoint (pptx)
    'application/x-hwp', 'application/haansofthwp', 'application/vnd.hancom.hwp', -- 한글 (hwp)
    'application/vnd.hancom.hwpx', 'application/haansofthwpx',                  -- 한글 (hwpx)
    'text/plain', 'text/csv', 'text/markdown'                                   -- 글 · CSV · 마크다운
  ]
)
on conflict (id) do update
  set file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- 2) 허용: docs 버킷 안에서만 올리기(insert)와 목록 보기·내려받기(select)
drop policy if exists "docs 올리기" on storage.objects;
create policy "docs 올리기" on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'docs');

drop policy if exists "docs 목록 보기" on storage.objects;
create policy "docs 목록 보기" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'docs');

-- 3) 확인: 아래 결과에 버킷 한 줄과 허용 두 줄(INSERT, SELECT)이 보이면 된다
select 'bucket' as 종류, id as 이름,
       case when public then '공개' else '비공개' end
         || ' · 한도 ' || coalesce((file_size_limit / 1048576)::text || 'MB', '없음')
         || ' · 문서 종류 ' || coalesce(array_length(allowed_mime_types, 1)::text || '가지', '제한 없음') as 내용
from storage.buckets
where id = 'docs'
union all
select 'policy', policyname, cmd || ' / ' || array_to_string(roles, ', ')
from pg_policies
where schemaname = 'storage' and tablename = 'objects' and policyname like 'docs %';
