-- 꽃사슴: 앱이 anon 키로 새 헤어샵 등록과 이직 등록을 저장할 수 있게 쓰기 권한을 연다
-- supabase_setup.sql 을 먼저 실행한 뒤, SQL Editor 에 붙여 넣고 Run 을 누르세요.
-- 로그인이 없으므로 키를 가진 누구나 쓸 수 있습니다. 지우기(delete)는 열지 않습니다.

-- 새 헤어샵 등록: salons 에 한 줄 추가
drop policy if exists "누구나 등록" on salons;
create policy "누구나 등록" on salons for insert with check (true);

-- 이직 등록: 새 디자이너 추가, 기존 디자이너 소속 변경, 이직 기록 추가
drop policy if exists "누구나 등록" on stylists;
create policy "누구나 등록" on stylists for insert with check (true);
drop policy if exists "누구나 소속 변경" on stylists;
create policy "누구나 소속 변경" on stylists for update using (true) with check (true);
drop policy if exists "누구나 등록" on moves;
create policy "누구나 등록" on moves for insert with check (true);
