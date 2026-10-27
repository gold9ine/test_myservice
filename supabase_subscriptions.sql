-- 구독 목록: data/76_subscriptions.csv 를 Supabase subscriptions 표로 만드는 SQL
-- Supabase 대시보드 > SQL Editor 에 붙여 넣고 Run 을 누르세요.
-- 다시 실행하면 표를 지우고 새로 만들어 CSV 12줄 상태로 돌아갑니다. 화면에서 넣고 고친 내용은 모두 사라집니다.

drop table if exists subscriptions;

create table subscriptions (
  id bigint generated always as identity primary key,  -- 줄 번호 (고치기·지우기 할 때 이 번호로 찾는다)
  name text not null,                                   -- 구독 이름
  category text,                                        -- 분류 (영상·음악·업무 등)
  monthly_fee integer,                                  -- 한 달 요금 (원)
  last_used date                                        -- 마지막으로 쓴 날
);

insert into subscriptions (name, category, monthly_fee, last_used) values
  ('영화 · 드라마 구독', '영상', 13500, '2026-10-18'),
  ('음악 구독', '음악', 10900, '2026-10-20'),
  ('클라우드 저장공간', '업무', 2400, '2026-10-19'),
  ('헬스장', '운동', 55000, '2026-03-02'),
  ('신문 구독', '읽을거리', 150000, '2026-10-21'),
  ('우유 배달', '먹거리', 18000, '2026-10-21'),
  ('정수기 렌털', '생활', 23900, '2026-10-21'),
  ('꽃 정기배송', '생활', 19800, '2026-09-28'),
  ('전자책 구독', '읽을거리', 9900, '2026-08-15'),
  ('반찬 정기배송', '먹거리', 64000, '2026-10-16'),
  ('커피 원두 정기배송', '먹거리', 17000, '2026-10-12'),
  ('문서 작성 도구', '업무', 8900, '2026-10-22');

-- 허용: 화면(anon 키)에서 읽기 · 넣기 · 고치기 · 지우기를 모두 할 수 있게 한다
alter table subscriptions enable row level security;
create policy "누구나 읽기" on subscriptions for select using (true);
create policy "누구나 넣기" on subscriptions for insert with check (true);
create policy "누구나 고치기" on subscriptions for update using (true) with check (true);
create policy "누구나 지우기" on subscriptions for delete using (true);
