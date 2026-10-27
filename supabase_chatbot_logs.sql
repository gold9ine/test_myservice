-- 꽃사슴 상담 챗봇: AI 가 답할 때마다 넣은 말과 받은 답을 남기는 표
-- Supabase 대시보드 > SQL Editor 에 붙여 넣고 Run 을 누르세요. 여러 번 실행해도 괜찮습니다.

create table if not exists chatbot_logs (
  id bigint generated always as identity primary key,
  question text not null,                          -- 사용자가 넣은 말
  answer text not null,                            -- AI 가 준 답
  tone text,                                       -- 고른 말투 (예: 친절한 존댓말)
  model text,                                      -- 답한 Gemini 모델 (예: gemini-3.5-flash-lite)
  created_at timestamptz not null default now()    -- 남긴 시각
);

-- 권한: 앱이 anon 키로 기록을 남기고(insert) 지난 기록을 읽을(select) 수 있게 한다. 고치기·지우기는 열지 않는다
alter table chatbot_logs enable row level security;
drop policy if exists "누구나 읽기" on chatbot_logs;
create policy "누구나 읽기" on chatbot_logs for select using (true);
drop policy if exists "누구나 남기기" on chatbot_logs;
create policy "누구나 남기기" on chatbot_logs for insert with check (true);
