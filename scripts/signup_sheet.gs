/**
 * 가입자 명단을 구글 시트에 모으는 Apps Script. office.html이 로그인할 때마다 여기로 보낸다.
 *
 * 처음 한 번만:
 * 1. 구글 시트를 새로 만든다 (이름 예: 마케팅팀 오피스 가입자).
 * 2. 확장 프로그램 → Apps Script를 열고, 기본 코드를 지운 뒤 이 파일 내용을 붙여넣고 저장한다.
 * 3. 배포 → 새 배포 → 유형 선택(톱니) → 웹 앱
 *      - 다음 사용자 인증 정보로 실행: 나
 *      - 액세스 권한이 있는 사용자: 모든 사용자
 *    → 배포 → 권한 승인 → 나오는 "웹 앱 URL"(https://script.google.com/macros/s/.../exec)을 복사한다.
 * 4. office.html의 SIGNUP_URL = "" 따옴표 안에 그 URL을 넣는다.
 *
 * 코드를 고쳤다면 배포 → 배포 관리 → 수정(연필) → 버전: 새 버전으로 다시 배포해야 반영된다 (URL은 그대로).
 *
 * 쓰기(doPost)는 명단과 기록 백업을 저장한다. 이미 있는 번호는 명단의 이름이 맞을 때만 고친다.
 * 읽기(doGet)는 세 가지만 한다.
 *   - 리더보드: 참여자의 닉네임·직급·XP·연속 읽기·업적 수
 *   - 기록 불러오기(action=restore): 전화번호와 이름이 맞는 사람에게 그 사람의 기록 백업 (10번 틀리면 1시간 잠금)
 *   - 승진 쿠폰(action=coupon): 전화번호와 이름이 맞고 그 레벨에 오른 사람에게 "쿠폰" 탭의 지금 코드
 *
 * 승진 쿠폰 코드는 "쿠폰" 탭의 "쿠폰 코드" 칸에 넣으면 바로 반영된다 (다시 배포할 필요 없음). 비워두면 "준비 중"으로 뜬다.
 * 누가 언제 어떤 코드를 받았는지는 "쿠폰 발급" 탭에 남는다.
 *
 * 스크랩·아이디어 메모 개수에 따라 뜨는 렛츠커리어 안내의 링크는 "연결 링크" 탭에서 바꾼다 (UTM 포함 전체 주소, 비우면 그 안내는 꺼짐).
 * 이것도 다시 배포할 필요 없이 바로 반영된다. 리더보드를 불러올 때 함께 내려간다.
 * 이름·전화번호·이메일 목록은 웹 앱 밖으로 나가지 않으므로, 명단 전체는 시트를 공유받은 사람만 볼 수 있다.
 * 기록 백업은 숨겨진 "기록" 탭에 있다 (보기 → 숨겨진 시트).
 */
const SHEET_NAME = "가입자";
const HEADER = ["이름", "닉네임", "전화번호", "이메일", "처음 가입", "최근 로그인", "로그인 횟수", "개인정보 동의", "구분",
  "XP", "레벨", "연속 읽기", "업적", "리더보드", "pid", "진행 갱신"];
const PROGRESS_COL = 10;  // "XP"부터
const BACKUP_SHEET = "기록", CHUNK = 45000, MAX_BACKUP = 450000;  // 칸 하나에 5만 자까지라 나눠 담는다
const COUPON_SHEET = "쿠폰", COUPON_LOG = "쿠폰 발급";
const COUPON_LEVELS = [[4, "대리"], [6, "차장"], [10, "CMO"]];
const LINK_SHEET = "연결 링크";
// [구분, 언제 뜨나, 처음 넣어 둘 링크]. 구분은 office.html의 PROMOS key와 같아야 한다.
const LINK_ROWS = [
  ["mktguidebook_guide", "스크랩 5개 → 마케팅 취준 총정리 자료집 (무료)", ""],
  ["interview_guide", "스크랩 10개 → 면접 준비 끝장 가이드북", ""],
  ["portfolio_challenge", "완성 아이디어 5개 → 포트폴리오 2주 완성 챌린지 (주 버튼)", ""],
  ["portfolio_template", "완성 아이디어 5개 → 포트폴리오 템플릿 무료 자료 (보조 버튼)", ""],
  ["coverletter_challenge", "지원 브랜드 아이디어 3개 → 자기소개서 2주 완성 챌린지", ""],
  ["ogonggo", "메인 화면 '오늘의 마케팅 채용 공고 보러가기' 버튼 (비우면 버튼 숨김)", ""],
];

// 시트를 열 때마다 "쿠폰"·"연결 링크" 탭과 새로 생긴 줄을 만들어 둔다 (배포와 상관없이 저장만 하면 동작)
function onOpen() {
  couponSheet();
  readLinks();
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);  // 동시에 들어와도 같은 사람이 두 줄로 생기지 않게
  try {
    const d = JSON.parse(e.postData.contents);
    const phone = fmtPhone(d.phone);
    if (!phone) return reply({ ok: false, error: "phone" });
    const name = clean(d.name, 20), nick = clean(d.nick, 20), email = clean(d.email, 100);
    const now = new Date();
    const prog = [num(d.xp, 100000), num(d.lv, 10) || 1, num(d.streak, 3650), num(d.badges, 100),
      d.board === false ? "비공개" : "공개", clean(d.pid, 32), now];

    const sh = sheet();
    const i = findRow(sh, 3, phone);
    if (i >= 0) {
      // 남의 번호로 기록을 덮어쓰지 못하게, 명단에 이름이 있으면 그 이름이 맞아야 고친다 (이름을 바꿀 땐 예전 이름으로 확인)
      const stored = String(sh.getRange(i + 2, 1).getValue());
      if (stored && norm(stored) !== norm(d.prevName || d.name)) return reply({ ok: false, error: "name" });
    }
    if (i < 0) {
      sh.appendRow([name, nick, phone, email, now, now, 1, clean(d.agreedAt, 30), d.legacy ? "기존 이용자" : "신규", ...prog]);
    } else {
      const row = i + 2;
      if (name) sh.getRange(row, 1).setValue(name);
      sh.getRange(row, 2).setValue(nick);
      if (email) sh.getRange(row, 4).setValue(email);
      if (d.agreedAt) sh.getRange(row, 8).setValue(clean(d.agreedAt, 30));
      if (d.event === "login") {
        sh.getRange(row, 6).setValue(now);
        sh.getRange(row, 7).setValue((Number(sh.getRange(row, 7).getValue()) || 0) + 1);
      }
      sh.getRange(row, PROGRESS_COL, 1, prog.length).setValues([prog]);
    }
    if (d.save) writeBackup(phone, String(d.save));
    return reply({ ok: true });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// 리더보드: XP 높은 순으로 최대 200명. 이름·전화번호·이메일은 넣지 않는다.
function doGet(e) {
  const q = (e && e.parameter) || {};
  if (q.action === "restore") return restore(q);
  if (q.action === "coupon") return coupon(q);
  couponSheet();  // 관리자가 코드를 넣을 탭을 미리 만들어 둔다
  const links = readLinks();
  const sh = sheet();
  const rows = Math.max(sh.getLastRow() - 1, 0);
  const all = rows ? sh.getRange(2, 1, rows, HEADER.length).getValues() : [];
  const p = PROGRESS_COL - 1;
  const out = all.filter(r => r[p + 4] === "공개" && r[p + 5])
    .map(r => ({ pid: String(r[p + 5]), nick: String(r[1]), xp: Number(r[p]) || 0, lv: Number(r[p + 1]) || 1,
      streak: Number(r[p + 2]) || 0, badges: Number(r[p + 3]) || 0 }))
    .sort((a, b) => b.xp - a.xp)
    .slice(0, 200);
  return reply({ ok: true, rows: out, links });
}

// 본인 확인: 번호가 명단에 있고 이름이 맞는지. 번호가 없으면 found: false, 이름이 다르면 match: false. 10번 틀리면 1시간 잠금.
function verify(q) {
  const phone = fmtPhone(q.phone);
  if (!phone) return { error: { ok: false, error: "phone" } };
  const cache = CacheService.getScriptCache(), key = "fail:" + phone;
  const fails = Number(cache.get(key)) || 0;
  if (fails >= 10) return { error: { ok: true, locked: true } };
  const sh = sheet(), i = findRow(sh, 3, phone);
  if (i < 0) return { error: { ok: true, found: false } };
  const stored = String(sh.getRange(i + 2, 1).getValue());
  if (stored && norm(stored) !== norm(q.name)) {
    cache.put(key, String(fails + 1), 3600);
    return { error: { ok: true, found: true, match: false } };
  }
  return { sh, phone, row: i + 2, name: stored || clean(q.name, 20) };
}

// 다른 기기에서 로그인할 때 기록을 돌려준다
function restore(q) {
  const v = verify(q);
  if (v.error) return reply(v.error);
  return reply({ ok: true, found: true, match: true, save: readBackup(v.phone) });
}

// 승진 쿠폰: 명단에 기록된 레벨이 그 쿠폰 레벨 이상이어야 준다. 코드가 비어 있으면 coupon: null
function coupon(q) {
  const v = verify(q);
  if (v.error) return reply(v.error);
  const lv = Number(q.lv), lvNow = Number(v.sh.getRange(v.row, PROGRESS_COL + 1).getValue()) || 1;
  if (!COUPON_LEVELS.some(c => c[0] === lv) || lvNow < lv) return reply({ ok: true, coupon: null });
  const cs = couponSheet();
  const r = cs.getRange(2, 1, Math.max(cs.getLastRow() - 1, 1), 6).getDisplayValues().find(x => Number(x[0]) === lv);
  const code = r ? r[2].trim() : "";
  if (!code) return reply({ ok: true, coupon: null });
  logCoupon(v, lv, code);
  return reply({ ok: true, coupon: { code, desc: r[3].trim(), until: r[4].trim(), link: /^https?:\/\//.test(r[5].trim()) ? r[5].trim() : "" } });
}

// 같은 사람·레벨·코드는 한 번만 남긴다
function logCoupon(v, lv, code) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(COUPON_LOG);
  if (!sh) {
    sh = ss.insertSheet(COUPON_LOG);
    sh.appendRow(["발급 시각", "이름", "전화번호", "레벨", "쿠폰 코드"]);
    sh.setFrozenRows(1);
    sh.getRange("C:C").setNumberFormat("@");
  }
  const n = Math.max(sh.getLastRow() - 1, 0);
  const seen = n && sh.getRange(2, 3, n, 3).getDisplayValues().some(r => r[0] === v.phone && Number(r[1]) === lv && r[2] === code);
  if (!seen) sh.appendRow([new Date(), v.name, v.phone, lv, code]);
}

// { 구분: 링크 }. http(s)로 시작하지 않으면 빈 값 (= 안내 꺼짐)
function readLinks() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(LINK_SHEET);
  if (!sh) {
    sh = ss.insertSheet(LINK_SHEET);
    sh.appendRow(["구분 (고치지 마세요)", "언제 뜨나", "링크 (UTM 포함 전체 주소, 비우면 안내 안 함)"]);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, 3).setFontWeight("bold");
    sh.getRange("C:C").setNumberFormat("@");
  }
  const rows = sh.getLastRow() > 1 ? sh.getRange(2, 1, sh.getLastRow() - 1, 3).getDisplayValues() : [];
  // 코드에 새 안내가 생기면 탭에 줄을 보탠다
  LINK_ROWS.filter(r => !rows.some(x => x[0] === r[0])).forEach(r => { sh.appendRow(r); rows.push(r); });
  const out = {};
  rows.forEach(r => { const u = String(r[2]).trim(); out[r[0]] = /^https?:\/\//.test(u) ? u : ""; });
  return out;
}

function couponSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(COUPON_SHEET);
  if (!sh) {
    sh = ss.insertSheet(COUPON_SHEET);
    sh.appendRow(["레벨", "직급", "쿠폰 코드", "안내 문구 (예: 포트폴리오 챌린지 20% 할인)", "사용 기한 (예: 2026-11-30)", "바로가기 링크 (https://...)"]);
    COUPON_LEVELS.forEach(([lv, title]) => sh.appendRow([lv, title, "", "", "", ""]));
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, 6).setFontWeight("bold");
    sh.getRange("C:F").setNumberFormat("@");  // 코드·날짜를 입력한 그대로 보이게
  }
  return sh;
}

function writeBackup(phone, json) {
  if (json.length > MAX_BACKUP) return;
  const sh = backupSheet(), i = findRow(sh, 1, phone);
  const row = i < 0 ? sh.getLastRow() + 1 : i + 2;
  // 조각이 =나 숫자로 시작하면 시트가 수식·숫자로 바꿔버리므로 앞에 ~를 붙여 둔다
  const chunks = [];
  for (let k = 0; k < json.length; k += CHUNK) chunks.push("~" + json.slice(k, k + CHUNK));
  sh.getRange(row, 1, 1, Math.max(sh.getLastColumn(), 2 + chunks.length)).clearContent();
  sh.getRange(row, 1, 1, 2 + chunks.length).setValues([[phone, new Date(), ...chunks]]);
}

function readBackup(phone) {
  const sh = backupSheet(), i = findRow(sh, 1, phone);
  if (i < 0) return null;
  const cells = sh.getRange(i + 2, 3, 1, Math.max(sh.getLastColumn() - 2, 1)).getValues()[0];
  try {
    return JSON.parse(cells.filter(c => String(c).startsWith("~")).map(c => String(c).slice(1)).join(""));
  } catch (err) {
    return null;
  }
}

function backupSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(BACKUP_SHEET);
  if (!sh) {
    sh = ss.insertSheet(BACKUP_SHEET);
    sh.appendRow(["전화번호", "백업 시각", "기록 (여러 칸에 나눠 저장)"]);
    sh.setFrozenRows(1);
    sh.getRange("A:A").setNumberFormat("@");
    sh.hideSheet();
  }
  return sh;
}

// 머리줄 아래에서 col 열 값이 phone인 줄의 위치 (0부터, 없으면 -1)
function findRow(sh, col, phone) {
  const rows = Math.max(sh.getLastRow() - 1, 0);
  return rows ? sh.getRange(2, col, rows, 1).getDisplayValues().map(r => r[0]).indexOf(phone) : -1;
}

function fmtPhone(v) {
  const d = String(v || "").replace(/\D/g, "");
  if (!/^01\d{8,9}$/.test(d)) return "";
  return d.length === 11 ? `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}` : `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
}

// 이름 비교는 띄어쓰기·대소문자를 무시한다
function norm(s) {
  return String(s || "").replace(/\s+/g, "").toLowerCase();
}

function sheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEADER.length).setFontWeight("bold");
    sh.getRange("C:C").setNumberFormat("@");  // 010 앞의 0이 사라지지 않게 글자로
  }
  return sh;
}

// 시트 수식으로 해석되지 않게 =, +, -, @로 시작하는 값 앞에 '를 붙인다
function clean(v, max) {
  const s = String(v || "").trim().slice(0, max);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function num(v, max) {
  return Math.max(0, Math.min(max, Math.floor(Number(v) || 0)));
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
