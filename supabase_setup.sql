-- 꽃사슴: data/*.csv 를 Supabase 표로 옮기는 SQL
-- Supabase 대시보드 > SQL Editor 에 통째로 붙여 넣고 Run 을 누르세요.
-- 여러 번 실행해도 이미 있는 표와 줄은 건너뜁니다.

create table if not exists salons (
  salon_id text primary key,
  name text not null,
  phone text,
  address text,
  lat double precision,
  lng double precision,
  owner_stylist_id text
);

create table if not exists stylists (
  stylist_id text primary key,
  name text not null,
  salon_id text references salons(salon_id),
  career_years integer
);

create table if not exists moves (
  move_id text primary key,
  stylist_id text references stylists(stylist_id),
  from_salon_id text references salons(salon_id),
  to_salon_id text references salons(salon_id),
  moved_on date
);

create table if not exists portfolios (
  portfolio_id text primary key,
  stylist_id text references stylists(stylist_id),
  title text,
  description text,
  year integer
);

create table if not exists join_requests (
  request_id text primary key,
  salon_id text references salons(salon_id),
  stylist_id text references stylists(stylist_id),
  message text,
  requested_on date
);

insert into salons (salon_id, name, phone, address, lat, lng, owner_stylist_id) values
  ('S01', '헤어스튜디오 봄', '063-000-0001', '전북특별자치도 전주시 완산구 고사동', 35.8203, 127.1430, 'ST01'),
  ('S02', '여름 헤어', '063-000-0002', '전북특별자치도 전주시 덕진구 덕진동1가', 35.8466, 127.1252, 'ST04'),
  ('S03', '가을살롱', '063-000-0003', '전북특별자치도 전주시 완산구 교동', 35.8122, 127.1612, 'ST06'),
  ('S04', '겨울 헤어랩', '063-000-0004', '전북특별자치도 전주시 완산구 효자동2가', 35.8069, 127.0987, 'ST08'),
  ('S05', '햇살 미용실', '063-000-0005', '전북특별자치도 전주시 덕진구 송천동2가', 35.8717, 127.1212, 'ST10'),
  ('S06', '바람 헤어', '063-000-0006', '전북특별자치도 전주시 완산구 서신동', 35.8311, 127.1155, 'ST11')
on conflict do nothing;

insert into stylists (stylist_id, name, salon_id, career_years) values
  ('ST01', '김하늘', 'S01', 12),
  ('ST02', '이도윤', 'S01', 6),
  ('ST03', '박서연', 'S01', 4),
  ('ST04', '최민준', 'S02', 10),
  ('ST05', '정유나', 'S02', 5),
  ('ST06', '강지호', 'S03', 9),
  ('ST07', '윤채원', 'S03', 3),
  ('ST08', '임서준', 'S04', 11),
  ('ST09', '한예린', 'S04', 7),
  ('ST10', '오태윤', 'S05', 15),
  ('ST11', '서지아', 'S06', 8),
  ('ST12', '신우진', 'S06', 2)
on conflict do nothing;

insert into moves (move_id, stylist_id, from_salon_id, to_salon_id, moved_on) values
  ('M01', 'ST05', 'S01', 'S02', '2026-03-02'),
  ('M02', 'ST07', 'S04', 'S03', '2026-05-11'),
  ('M03', 'ST12', 'S02', 'S06', '2026-07-20'),
  ('M04', 'ST09', 'S05', 'S04', '2026-08-03'),
  ('M05', 'ST02', 'S03', 'S01', '2026-09-14')
on conflict do nothing;

insert into portfolios (portfolio_id, stylist_id, title, description, year) values
  ('P01', 'ST01', '남성 커트 전문', '투블럭과 댄디컷 위주로 12년째 남성 커트를 하고 있습니다.', 2026),
  ('P02', 'ST01', '헤어 아카데미 강사', '신입 디자이너 대상 커트 기초 강의를 맡았습니다.', 2024),
  ('P03', 'ST02', '손상모 케어', '잦은 염색으로 상한 머리를 위한 클리닉 시술을 주로 합니다.', 2026),
  ('P04', 'ST03', '단발 레이어드 커트', '얼굴형에 맞춘 단발 레이어드 커트를 연구하고 있습니다.', 2025),
  ('P05', 'ST04', '펌 전문 디자이너', '볼륨매직과 C컬 펌을 10년째 하고 있습니다.', 2026),
  ('P06', 'ST05', '애쉬 계열 염색', '탈색 횟수를 줄인 애쉬 브라운 염색을 잘합니다.', 2026),
  ('P07', 'ST06', '웨딩 헤어 스타일링', '결혼식과 촬영용 업스타일을 맡고 있습니다.', 2025),
  ('P08', 'ST07', '곱슬머리 매직', '곱슬이 심한 모발의 매직 스트레이트를 주로 합니다.', 2026),
  ('P09', 'ST08', '디자이너 교육 담당', '살롱 내 신입 디자이너 교육을 맡고 있습니다.', 2026),
  ('P10', 'ST08', '헤어 대회 수상', '서울 지역 헤어 경연대회 커트 부문에서 입상했습니다.', 2023),
  ('P11', 'ST09', '두피 케어', '두피 스케일링과 탈모 예방 관리를 함께 합니다.', 2026),
  ('P12', 'ST10', '15년 경력 원장', '오래 다닌 단골 고객 위주로 커트와 펌을 합니다.', 2026),
  ('P13', 'ST11', '숏컷 전문', '여성 숏컷과 픽시컷 스타일을 주로 합니다.', 2026),
  ('P14', 'ST12', '신입 디자이너', '어시스턴트 3년을 마치고 디자이너로 시작했습니다.', 2026)
on conflict do nothing;

insert into join_requests (request_id, salon_id, stylist_id, message, requested_on) values
  ('R01', 'S02', 'ST05', '다음 달부터 여름 헤어에서 일하게 되었습니다. 소속 디자이너로 등록 부탁드립니다.', '2026-02-25'),
  ('R02', 'S03', 'ST07', '5월부터 가을살롱으로 옮깁니다. 예전 고객분들이 찾으실 수 있게 등록 요청드립니다.', '2026-05-06'),
  ('R03', 'S06', 'ST12', '바람 헤어에서 디자이너로 새로 시작합니다. 소속 등록 부탁드립니다.', '2026-07-15'),
  ('R04', 'S04', 'ST09', '8월부터 겨울 헤어랩 소속으로 일하게 되었습니다. 확인 부탁드립니다.', '2026-07-29'),
  ('R05', 'S01', 'ST02', '헤어스튜디오 봄으로 다시 돌아가게 되었습니다. 등록 부탁드립니다.', '2026-09-10'),
  ('R06', 'S05', 'ST03', '11월에 햇살 미용실로 옮길 예정입니다. 미리 등록 요청드립니다.', '2026-10-06')
on conflict do nothing;

-- 헤어샵 주인(owner_stylist_id)은 디자이너 표가 채워진 뒤에 연결한다
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'salons_owner_stylist_id_fkey') then
    alter table salons add constraint salons_owner_stylist_id_fkey
      foreign key (owner_stylist_id) references stylists(stylist_id);
  end if;
end $$;

-- 읽기 권한: 앱이 anon 키로 모든 표를 읽을 수 있게 한다 (쓰기는 열지 않음)
alter table salons enable row level security;
drop policy if exists "누구나 읽기" on salons;
create policy "누구나 읽기" on salons for select using (true);
alter table stylists enable row level security;
drop policy if exists "누구나 읽기" on stylists;
create policy "누구나 읽기" on stylists for select using (true);
alter table moves enable row level security;
drop policy if exists "누구나 읽기" on moves;
create policy "누구나 읽기" on moves for select using (true);
alter table portfolios enable row level security;
drop policy if exists "누구나 읽기" on portfolios;
create policy "누구나 읽기" on portfolios for select using (true);
alter table join_requests enable row level security;
drop policy if exists "누구나 읽기" on join_requests;
create policy "누구나 읽기" on join_requests for select using (true);
