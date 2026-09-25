"""단어장으로 세 가지 시험지를 만든다.

- 영영 풀이 연결: 단어-영영 풀이 다섯 쌍 중 틀린 쌍 하나를 고른다.
- 영어 → 한국어: 영단어를 주고 한국어 뜻을 빈칸으로 쓴다.
- 한국어 → 영어: 한국어 뜻을 주고 영단어를 빈칸으로 쓴다.
"""

import csv
import random
import re
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pymupdf as fitz


BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# 어휘끝 수능편 1,572단어의 영영 풀이. 교재의 한국어 뜻에 맞춰 쓰고 Cambridge 사전과 대조했다.
BUILTIN_PATH = BASE / "어휘끝_수능편_영영풀이.csv"
MATCH, EN_TO_KO, KO_TO_EN = "match", "en2ko", "ko2en"
MODES = {
    "영영 풀이 연결": MATCH,
    "영어 → 한국어 뜻 쓰기": EN_TO_KO,
    "한국어 → 영어 단어 쓰기": KO_TO_EN,
}
MODE_TITLES = {
    MATCH: ("영영 풀이 문제", "다음 각 문항에서 단어와 영영 풀이의 연결이 틀린 것을 고르시오."),
    EN_TO_KO: ("영단어 뜻 쓰기", "다음 영단어의 뜻을 우리말로 쓰시오."),
    KO_TO_EN: ("영단어 쓰기", "다음 우리말 뜻에 알맞은 영단어를 쓰시오."),
}
HANGUL_RE = re.compile(r"[가-힣]")
DAY_RE = re.compile(r"\bday\s*[-:]?\s*(\d+)\b", re.I)
SECTION_RE = re.compile(r"(?:day|unit|lesson|chapter|week)\s*[-:.]?\s*(\d+)", re.I)
PAIR_RE = re.compile(r"^\s*([A-Za-z][A-Za-z '-]{0,45})\s*:\s*(.{10,})\s*$")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z '-]{0,45}")
POS_RE = re.compile(r"\[(n|v|adj|adv|pron|prep|conj|interj)\]")
COMMON_WORDS = {"about", "after", "again", "being", "could", "every", "having", "other", "their", "there", "these", "thing", "things", "those", "which", "while", "with", "would"}
CIRCLED = "①②③④⑤"
SENSE_SPLIT_RE = re.compile(r";\s*(?=\[)")
POS_TAG_RE = re.compile(r"^\[([a-z]+)\]")
PDF_INK = (0.098, 0.239, 0.263)
PDF_GOLD = (0.773, 0.659, 0.459)
PDF_BODY = (0.118, 0.149, 0.157)
PDF_MUTED = (0.443, 0.506, 0.498)
PDF_HAIR = (0.855, 0.886, 0.875)
PDF_FAINT = (0.760, 0.800, 0.788)


_builtin_cache = None


def builtin_definitions():
    """내장 영영 풀이 {단어: 풀이}. 파일이 없으면 빈 사전."""
    global _builtin_cache
    if _builtin_cache is None:
        _builtin_cache = {}
        try:
            with BUILTIN_PATH.open(encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    word, definition = (row.get("word") or "").strip(), (row.get("definition") or "").strip()
                    if word and definition:
                        _builtin_cache[word.casefold()] = definition
        except OSError:
            pass
    return _builtin_cache


def read_words(path):
    """단어장을 (단원, 단어, 영영 풀이, 난이도, 한국어 뜻) 목록으로 읽는다.

    영영 풀이가 비어 있는 단어는 어휘끝 내장 풀이로 채운다. 내장 풀이에도 없는 단어(다른 단어장)는
    풀이가 비고, 그 단어장으로는 빈칸 문제만 만든다.
    """
    builtin = builtin_definitions()
    return [
        (day, word, definition or builtin.get(word.casefold(), ""), level, korean)
        for day, word, definition, level, korean in _read_raw(Path(path))
    ]


def _read_raw(path):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required = {"day", "word"}
            if not required <= set(reader.fieldnames or []):
                raise ValueError("CSV 첫 줄에는 day,word 열이 필요합니다. definition(영영 풀이), korean(한국어 뜻), difficulty 열은 선택입니다.")
            rows = []
            for line, row in enumerate(reader, 2):
                try:
                    day = int(row["day"])
                    level = int(row.get("difficulty") or 2)
                except (TypeError, ValueError):
                    raise ValueError(f"CSV {line}행: day와 difficulty는 숫자여야 합니다.") from None
                word = (row["word"] or "").strip()
                definition = (row.get("definition") or "").strip()
                korean = (row.get("korean") or "").strip()
                if day < 1 or level not in (1, 2, 3) or not word:
                    raise ValueError(f"CSV {line}행: day, word, difficulty를 확인하세요.")
                rows.append((day, word, definition, level, korean))
            return rows
    if path.suffix.lower() == ".pdf":
        pairs = []
        columns = []
        pages = []
        sizes = {}
        word_sizes = {}
        section = 0
        with fitz.open(path) as pdf:
            for page in pdf:
                page_text = page.get_text("text")
                spans = [
                    span
                    for block in page.get_text("dict")["blocks"]
                    for line in block.get("lines", [])
                    for span in line["spans"]
                    if span["text"].strip()
                ]
                # 단원 번호는 큰 글씨 표제에서 읽고, 표제가 없는 페이지는 앞 단원을 이어받는다.
                heading = 0
                for span in spans:
                    found = SECTION_RE.fullmatch(span["text"].strip())
                    if found and span["size"] >= 13:
                        heading = int(found.group(1))
                        break
                if heading:
                    section = heading
                for span in spans:
                    key = round(span["size"], 1)
                    sizes[key] = sizes.get(key, 0) + 1
                    if WORD_RE.fullmatch(span["text"].strip()):
                        word_sizes[key] = word_sizes.get(key, 0) + 1
                pages.append((section, spans))

                # 'DAY n' 머리글을 쓰는 단어장(워드마스터)은 기존 방식 그대로 읽는다.
                found_day = DAY_RE.search(page_text[:250])
                if not found_day:
                    continue
                day = int(found_day.group(1))
                for line in page_text.splitlines():
                    pair = PAIR_RE.fullmatch(line)
                    if pair:
                        pairs.append((day, pair.group(1).strip(), pair.group(2).strip(), 2, ""))
                for span in spans:
                    x = span["bbox"][0]
                    word = span["text"].strip()
                    if (45 <= x <= 70 or 305 <= x <= 345) and WORD_RE.fullmatch(word):
                        columns.append((day, word, "", 2, ""))
        if pairs:
            return pairs
        if len(columns) >= 30:
            return columns

        # 표제어를 본문보다 큰 글씨로 찍는 단어장(어휘끝 등)은 글자 크기로 가려낸다.
        headword = _headword_size(sizes, word_sizes)
        if headword:
            sized = _sized_headwords(pages, headword)
            if len(sized) >= 30:
                return sized
        raise ValueError(
            "PDF에서 단원별 영단어를 찾지 못했습니다. DAY 또는 Unit 번호가 있고 글자를 마우스로 "
            "선택할 수 있는 단어장 PDF인지 확인하세요. 스캔한 이미지 PDF는 읽지 못합니다."
        )
    raise ValueError("CSV 또는 PDF 파일을 선택하세요.")


def _sized_headwords(pages, headword):
    """표제어 크기 글씨를 단어로, 바로 뒤의 한글 줄을 한국어 뜻으로 읽는다.

    'medieval/mediaev' + 'al'처럼 칸이 좁아 두 줄로 찍힌 표제어는 이어 붙이고 '/' 앞 철자만 쓴다.
    한국어 뜻이 붙은 표제어가 대부분인 단어장에서는 뜻이 없는 큰 글씨(부록 제목 등)를 버린다.
    """
    found = []
    for number, spans in pages:
        if not number:
            continue
        index = 0
        while index < len(spans):
            span = spans[index]
            index += 1
            if round(span["size"], 1) != headword:
                continue
            text = span["text"].strip()
            while "/" in text and index < len(spans) and round(spans[index]["size"], 1) == headword:
                text += spans[index]["text"].strip()
                index += 1
            word = text.split("/")[0].strip()
            if not WORD_RE.fullmatch(word):
                continue
            korean = ""
            if index < len(spans) and round(spans[index]["size"], 1) != headword:
                # 한 줄의 뜻이 여러 조각(사이에 \x01 같은 제어 문자)으로 나뉘어 찍힌 쪽이 있어 같은 줄을 모두 잇는다.
                top = spans[index]["bbox"][1]
                pieces = []
                while index < len(spans) and abs(spans[index]["bbox"][1] - top) < 1.5 and round(spans[index]["size"], 1) != headword:
                    pieces.append(spans[index]["text"])
                    index += 1
                following = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f]", " ", "".join(pieces))).strip()
                korean = following if HANGUL_RE.search(following) else ""
            found.append((number, word, "", 2, korean))
    if sum(bool(item[4]) for item in found) >= len(found) * 0.8:
        found = [item for item in found if item[4]]
    return found


def _headword_size(sizes, word_sizes):
    """본문보다 크면서 영단어만 가장 많이 찍힌 글자 크기를 표제어 크기로 본다."""
    if not sizes or not word_sizes:
        return 0
    body = max(sizes, key=lambda key: sizes[key])
    best = 0
    for size, count in word_sizes.items():
        if size > body + 0.5 and count >= 30 and count > word_sizes.get(best, 0):
            best = size
    return best


def blank_pool(rows, first_day, last_day, difficulty):
    """빈칸 문제에 쓸 (단어, 한국어 뜻) 목록. 단어나 뜻이 겹치면 정답이 둘이 되므로 한 번만 넣는다."""
    pool = []
    words, meanings = set(), set()
    for day, word, _, level, korean in rows:
        if not korean or not (first_day <= day <= last_day) or (difficulty and difficulty != level):
            continue
        if word.casefold() in words or korean in meanings:
            continue
        words.add(word.casefold())
        meanings.add(korean)
        pool.append((word, korean))
    return pool


def make_blank_questions(rows, first_day, last_day, difficulty, count, rng=None):
    """빈칸 문제는 (영단어, 한국어 뜻) 목록이다. 방향(영→한, 한→영)은 조판할 때 정한다."""
    rng = rng or random.Random()
    if first_day > last_day:
        raise ValueError("시작 단원이 끝 단원보다 클 수 없습니다.")
    pool = blank_pool(rows, first_day, last_day, difficulty)
    if not pool:
        raise ValueError("선택한 범위에 한국어 뜻이 있는 단어가 없습니다. 한국어 뜻이 들어 있는 단어장(어휘끝 PDF 또는 korean 열이 있는 CSV)을 쓰세요.")
    if count < 1 or count > len(pool):
        raise ValueError(f"문제 수는 1~{len(pool)}개로 입력하세요.")
    return rng.sample(pool, count)


def max_questions(rows, first_day, last_day, difficulty, mode=MATCH):
    """선택 범위에서 중복 없이 만들 수 있는 최대 문항 수.

    영영 풀이 연결은 한 문제에 단어 5개가 들어가고, 범위의 모든 단어에 영영 풀이가 있어야 한다
    (어휘끝이 아닌 단어장은 풀이가 없어 0). 빈칸 문제는 한 문제에 단어 하나다.
    """
    if mode != MATCH:
        return len(blank_pool(rows, first_day, last_day, difficulty))
    selected = [row for row in rows if first_day <= row[0] <= last_day and not (difficulty and difficulty != row[3])]
    if not selected or not all(row[2] for row in selected):
        return 0
    words = set()
    definitions = set()
    for _, word, definition, _, _ in selected:
        key, meaning = word.casefold(), definition.casefold()
        if key in words or meaning in definitions:
            continue
        words.add(key)
        definitions.add(meaning)
    return len(words) // 5


def missing_definitions(rows, first_day, last_day, difficulty):
    """범위 안에서 영영 풀이가 없는 단어 수."""
    return sum(1 for row in rows if first_day <= row[0] <= last_day and not (difficulty and difficulty != row[3]) and not row[2])


def make_questions(rows, first_day, last_day, difficulty, count, rng=None):
    rng = rng or random.Random()
    if first_day > last_day:
        raise ValueError("시작 단원이 끝 단원보다 클 수 없습니다.")
    pool = []
    seen_words = set()
    seen_definitions = set()
    for day, word, definition, level, _ in rows:
        key = word.casefold()
        meaning = definition.casefold()
        if first_day <= day <= last_day and (difficulty == 0 or level == difficulty) and key not in seen_words and meaning not in seen_definitions:
            pool.append((day, word, definition))
            seen_words.add(key)
            seen_definitions.add(meaning)
    if len(pool) < 6:
        raise ValueError(f"선택한 범위에서 중복 없는 단어·풀이가 {len(pool)}개입니다. 한 문제에 최소 6개가 필요합니다.")
    maximum = len(pool) // 5
    if count < 1 or count > maximum:
        raise ValueError(f"같은 단어를 반복하지 않으려면 문제 수는 1~{maximum}개로 입력하세요. 현재 단어·풀이 {len(pool)}개가 있습니다.")

    questions = []
    selected = rng.sample(pool, count * 5)
    extras = [item for item in pool if item not in selected]
    for offset in range(0, len(selected), 5):
        choices = selected[offset:offset + 5]
        question = make_one_question(choices + extras if extras else pool, choices, rng)
        questions.append(question)
        extras = [item for item in extras if item[2] != question[0][question[1] - 1][1]]
    return questions


def decoy_score(word, definition, decoy_definition):
    """품사가 다르고 설명 어휘가 덜 겹치는 오답을 우선한다."""
    source_pos = set(POS_RE.findall(definition))
    decoy_pos = set(POS_RE.findall(decoy_definition))
    pos_penalty = 0 if source_pos and decoy_pos and source_pos.isdisjoint(decoy_pos) else 1
    def tokens(text):
        return {term for term in re.findall(r"[a-z]{5,}", text.casefold()) if term not in COMMON_WORDS}
    source_tokens, decoy_tokens = tokens(definition), tokens(decoy_definition)
    overlap = len(source_tokens & decoy_tokens) / max(1, min(len(source_tokens), len(decoy_tokens)))
    word_penalty = 1 if re.search(rf"\b{re.escape(word.casefold())}\b", decoy_definition.casefold()) else 0
    return (pos_penalty, word_penalty, overlap)


def make_one_question(pool, choices, rng=None, avoid=None):
    rng = rng or random.Random()
    candidates = []
    outside = [item for item in pool if item not in choices]
    for wrong in choices:
        for decoy in rng.sample(outside, min(40, len(outside))):
            if (wrong[1], decoy[2]) == avoid:
                continue
            candidates.append((decoy_score(wrong[1], wrong[2], decoy[2]), wrong, decoy))
    if not candidates:
        raise ValueError("새 오답을 만들 단어가 부족합니다. 단원 범위를 늘리세요.")
    best = min(score for score, _, _ in candidates)
    _, wrong_word, decoy = rng.choice([item for item in candidates if item[0] == best])
    options = [(word, decoy[2] if item == wrong_word else definition) for item in choices for _, word, definition in [item]]
    rng.shuffle(options)
    answer = next(i + 1 for i, (word, _) in enumerate(options) if word == wrong_word[1])
    return (options, answer, wrong_word[1], wrong_word[2])


def format_exam(questions, show_answers=False, mode=MATCH):
    lines = [*MODE_TITLES[mode], ""]
    if mode != MATCH:
        for number, (word, korean) in enumerate(questions, 1):
            prompt, answer = (word, korean) if mode == EN_TO_KO else (korean, word)
            lines.append(f"{number:02d}   {prompt}   ( {answer if show_answers else '                    '} )")
        return "\n".join(lines)
    for number, (options, _, _, _) in enumerate(questions, 1):
        lines.append(f"{number:02d}")
        lines.extend(f"   {CIRCLED[i]}  {word} — {definition}" for i, (word, definition) in enumerate(options))
        lines.append("")
    if show_answers:
        lines.extend(["정답 및 해설", ""])
        for number, (_, answer, word, definition) in enumerate(questions, 1):
            lines.append(f"{number:02d}  {CIRCLED[answer - 1]}  {word} — {definition}")
    return "\n".join(lines)


def _find_font(name):
    for candidate in (BASE / name, Path(r"C:\Windows\Fonts") / name):
        if candidate.exists():
            return candidate
    return None


def _definition_runs(definition):
    """[pos] 표지는 이탤릭 회색, 뜻풀이는 로만체. 두 번째 뜻은 가운뎃점으로 나눈다."""
    runs = []
    senses = [part.strip() for part in SENSE_SPLIT_RE.split(definition) if part.strip()]
    previous = ""
    for index, sense in enumerate(senses):
        if index:
            runs.append(("· ", "tiro", PDF_GOLD))
        tag = POS_TAG_RE.match(sense)
        if tag:
            if tag.group(1) != previous:
                runs.append((f"{tag.group(1)} ", "tiit", PDF_MUTED))
            previous = tag.group(1)
            sense = sense[tag.end():].strip()
        if sense:
            runs.append((sense[:1].lower() + sense[1:].rstrip(". ") + " ", "tiro", PDF_BODY))
    return runs or [(definition, "tiro", PDF_BODY)]


class _Sheet:
    """A4 편집 그리드. 한글은 맑은 고딕, 영어 표제어·풀이는 세리프로 짜는 사전 조판."""

    MARGIN = 56
    TOP = 62

    def __init__(self, kind, stamp="", mode=MATCH):
        regular = _find_font("malgun.ttf")
        if regular is None:
            raise ValueError("PDF에 필요한 맑은 고딕 글꼴을 찾지 못했습니다.")
        bold = _find_font("malgunbd.ttf") or regular
        self.files = {"kr": str(regular), "krb": str(bold)}
        self.metrics = {
            "kr": fitz.Font(fontfile=str(regular)),
            "krb": fitz.Font(fontfile=str(bold)),
            "tiro": fitz.Font("tiro"),
            "tibo": fitz.Font("tibo"),
            "tiit": fitz.Font("tiit"),
        }
        self.kind = kind
        self.stamp = stamp
        title, guide = MODE_TITLES[mode]
        if kind == "answers":
            title = "영영 풀이 정답지" if mode == MATCH else f"{title} 정답지"
            guide = "각 문항의 정답 번호와, 오답으로 제시된 단어의 올바른 풀이입니다." if mode == MATCH else "각 문항의 정답입니다."
        self.title, self.guide = title, guide
        self.doc = fitz.open()
        self.width, self.height = fitz.paper_size("a4")
        self.left = self.MARGIN
        self.right = self.width - self.MARGIN
        self.bottom = self.height - 66
        self.page = None
        self.y = 0
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page(width=self.width, height=self.height)
        for name, file in self.files.items():
            self.page.insert_font(fontname=name, fontfile=file)
        self.y = self.TOP
        self.masthead() if len(self.doc) == 1 else self.running_head()

    def measure(self, string, font, size):
        return self.metrics[font].text_length(string, fontsize=size)

    def text(self, x, y, string, font="kr", size=10, color=PDF_BODY):
        if string:
            self.page.insert_text((x, y), string, fontname=font, fontsize=size, color=color)
        return x + self.measure(string, font, size)

    def tracked(self, x, y, string, font="krb", size=8, color=PDF_GOLD, space=1.7):
        for char in string:
            x = self.text(x, y, char, font, size, color) + space
        return x

    def rule(self, y, x0=None, x1=None, color=PDF_HAIR, width=0.6):
        self.page.draw_line(
            fitz.Point(self.left if x0 is None else x0, y),
            fitz.Point(self.right if x1 is None else x1, y),
            color=color,
            width=width,
        )

    def masthead(self):
        y = self.y
        self.tracked(self.left, y, "LEXICON  ·  WORKSHEET")
        if self.stamp:
            self.text(self.right - self.measure(self.stamp, "kr", 8), y, self.stamp, "kr", 8, PDF_MUTED)
        y += 10
        self.rule(y, color=PDF_GOLD, width=1.2)
        y += 30
        self.text(self.left, y, self.title, "krb", 21, PDF_INK)
        y += 20
        self.text(self.left, y, self.guide, "kr", 9.5, PDF_MUTED)
        if self.kind != "answers":
            field = "이름                          점수"
            start = self.right - self.measure(field, "kr", 9)
            self.text(start, y, field, "kr", 9, PDF_MUTED)
            self.rule(y + 3.5, start - 6, self.right, PDF_HAIR, 0.5)
        y += 15
        self.rule(y)
        self.y = y + 30

    def running_head(self):
        y = self.y - 16
        self.text(self.left, y, self.title, "kr", 8, PDF_MUTED)
        self.tracked(self.right - 62, y, "LEXICON", size=7.5, color=PDF_FAINT)
        self.rule(y + 7, width=0.5)
        self.y = y + 30

    def footer(self):
        total = len(self.doc)
        for index, page in enumerate(self.doc, 1):
            base = self.height - 42
            page.draw_line(fitz.Point(self.left, base - 13), fitz.Point(self.right, base - 13), color=PDF_HAIR, width=0.5)
            page.insert_text((self.left, base), "LEXICON · 영영 풀이 문제 생성기", fontname="kr", fontsize=7.5, color=PDF_MUTED)
            stamp = f"{index} / {total}"
            page.insert_text(
                (self.right - self.metrics["tiro"].text_length(stamp, fontsize=8.5), base),
                stamp, fontname="tiro", fontsize=8.5, color=PDF_MUTED,
            )

    def ensure(self, needed):
        if self.y + needed > self.bottom:
            self.new_page()

    def flow(self, runs, hang, size=9.6, leading=13.6, dry=False):
        """(텍스트, 폰트, 색) 조각을 한 단락으로 흘리고, 넘치면 hang 위치로 들여 접는다."""
        x = hang
        lines = 1
        for string, font, color in runs:
            for token in re.findall(r"\S+\s*", string):
                word = token.rstrip()
                if x > hang and x + self.measure(word, font, size) > self.right:
                    lines += 1
                    x = hang
                    if not dry:
                        self.y += leading
                        self.ensure(leading)
                if not dry:
                    self.text(x, self.y, word, font, size, color)
                x += self.measure(token, font, size)
        return lines

    def block_height(self, runs, size=9.6, leading=13.6):
        return self.flow(runs, self.left + 152, size, leading, dry=True) * leading

    def save(self, path):
        self.footer()
        try:
            self.doc.subset_fonts(verbose=False)
        except Exception:
            pass
        self.doc.save(path, garbage=4, deflate=True)
        self.doc.close()


def _save_blank_pdf(path, questions, answers, mode):
    """빈칸 문제: 번호 · 제시어 · 답칸. 정답지는 답칸 자리에 정답을 적는다."""
    sheet = _Sheet("answers" if answers else "exam", f"문항 {len(questions)}개", mode)
    prompt_x = sheet.left + 34
    if mode == EN_TO_KO:
        prompt_right, blank_x = sheet.left + 196, sheet.left + 206
        prompt_run = lambda word, korean: [(word, "tibo", PDF_INK)]
        answer_run = lambda word, korean: [(korean, "kr", PDF_INK)]
    else:
        prompt_right, blank_x = sheet.right - 164, sheet.right - 150
        prompt_run = lambda word, korean: [(korean, "kr", PDF_BODY)]
        answer_run = lambda word, korean: [(word, "tibo", PDF_INK)]
    right = sheet.right

    def lines(runs, x0, x1, size):
        sheet.right = x1
        count = sheet.flow(runs, x0, size, 15, dry=True)
        sheet.right = right
        return count

    for number, (word, korean) in enumerate(questions, 1):
        prompt, answer = prompt_run(word, korean), answer_run(word, korean)
        height = max(lines(prompt, prompt_x, prompt_right, 10.5), lines(answer, blank_x + 6, right, 10.5) if answers else 1) * 15
        sheet.ensure(height + 14)
        top = sheet.y
        sheet.text(sheet.left, top, f"{number:02d}", "krb", 9.5, PDF_MUTED)
        sheet.right = prompt_right
        sheet.flow(prompt, prompt_x, 10.5, 15)
        sheet.right = right
        bottom = sheet.y
        sheet.y = top
        if answers:
            sheet.flow(answer, blank_x + 6, 10.5, 15)
        else:
            sheet.rule(top + 4, blank_x, right, PDF_FAINT, 0.7)
        sheet.y = max(bottom, sheet.y) + 8
        sheet.rule(sheet.y, color=PDF_HAIR, width=0.4)
        sheet.y += 18
    sheet.save(path)


def save_pdf(path, questions, answers=False, mode=MATCH):
    """A4 시험지 또는 정답지를 편집 그리드에 맞춰 조판한다."""
    if mode != MATCH:
        _save_blank_pdf(path, questions, answers, mode)
        return
    sheet = _Sheet("answers" if answers else "exam", f"문항 {len(questions)}개")
    word_x = sheet.left + 36
    def_x = sheet.left + 152

    if answers:
        sheet.text(sheet.left, sheet.y, "정답 일람", "krb", 10.5, PDF_INK)
        sheet.y += 16
        columns = 10
        cell = (sheet.right - sheet.left) / columns
        for row in range(0, len(questions), columns):
            sheet.ensure(40)
            top = sheet.y
            for column, (_, answer, _, _) in enumerate(questions[row:row + columns]):
                x = sheet.left + column * cell
                sheet.page.draw_rect(fitz.Rect(x, top, x + cell, top + 36), color=PDF_HAIR, width=0.5)
                label = f"{row + column + 1:02d}"
                sheet.text(x + (cell - sheet.measure(label, "tiro", 7.5)) / 2, top + 13, label, "tiro", 7.5, PDF_MUTED)
                mark = CIRCLED[answer - 1]
                sheet.text(x + (cell - sheet.measure(mark, "krb", 12)) / 2, top + 30, mark, "krb", 12, PDF_INK)
            sheet.y = top + 36
        sheet.y += 34

        sheet.text(sheet.left, sheet.y, "해설", "krb", 10.5, PDF_INK)
        sheet.y += 9
        sheet.rule(sheet.y, color=PDF_GOLD, width=1.0)
        sheet.y += 24
        for number, (_, answer, word, definition) in enumerate(questions, 1):
            sheet.ensure(34)
            sheet.text(sheet.left, sheet.y, f"{number:02d}", "krb", 9.5, PDF_MUTED)
            sheet.text(sheet.left + 23, sheet.y, CIRCLED[answer - 1], "kr", 10.5, PDF_INK)
            sheet.text(word_x + 8, sheet.y, word, "tibo", 10.4, PDF_INK)
            if word_x + 8 + sheet.measure(word, "tibo", 10.4) + 12 > def_x:
                sheet.y += 13.6
                sheet.ensure(13.6)
            sheet.flow(_definition_runs(definition), def_x)
            sheet.y += 20
        sheet.save(path)
        return

    for number, (options, _, _, _) in enumerate(questions, 1):
        needed = 20 + sum(
            sheet.block_height(_definition_runs(text)) + 1.8
            + (13.6 if word_x + sheet.measure(name, "tibo", 10.2) + 12 > def_x else 0)
            for name, text in options
        )
        if sheet.y + needed > sheet.bottom and sheet.y > sheet.TOP + 40:
            sheet.new_page()
        label = f"{number:02d}"
        sheet.text(sheet.left, sheet.y, label, "krb", 12.5, PDF_INK)
        sheet.rule(sheet.y - 4, sheet.left + sheet.measure(label, "krb", 12.5) + 12, sheet.right, PDF_HAIR, 0.7)
        sheet.y += 20

        for index, (option_word, option_definition) in enumerate(options):
            sheet.ensure(16)
            sheet.text(sheet.left + 13, sheet.y, CIRCLED[index], "kr", 10, PDF_INK)
            sheet.text(word_x, sheet.y, option_word, "tibo", 10.2, PDF_INK)
            if word_x + sheet.measure(option_word, "tibo", 10.2) + 12 > def_x:
                sheet.y += 13.6
                sheet.ensure(13.6)
            sheet.flow(_definition_runs(option_definition), def_x)
            sheet.y += 15.4
        sheet.y += 16

    sheet.save(path)


class App:
    def __init__(self, root):
        self.root = root
        root.title("LEXICON | 영영 풀이 문제 생성기")
        root.geometry("1120x780")
        root.minsize(980, 740)
        root.configure(bg="#F3F5F4")
        self.rows = []
        self.resolved_rows = []
        self.questions = []
        self.reviewed = []
        self.review_window = None
        self.file_label = tk.StringVar(value="단어장을 불러오세요")
        self.source_label = tk.StringVar(value="파일을 선택하면 단원과 단어 수를 표시합니다.")
        self.review_label = tk.StringVar(value="문제를 만든 뒤 검토해 주세요")
        self.first = tk.StringVar(value="1")
        self.last = tk.StringVar(value="5")
        self.level = tk.StringVar(value="보통 (2)")
        self.mode = tk.StringVar(value="영영 풀이 연결")
        self.question_mode = MATCH
        self.count = tk.StringVar(value="5")
        self.limit_text = tk.StringVar(value="단어장을 불러오면 최대 문항 수를 알려드립니다.")
        self.limit = 0
        for variable in (self.first, self.last, self.level, self.mode):
            variable.trace_add("write", lambda *_: self.refresh_limit())
        self.count.trace_add("write", lambda *_: self.clamp_count())
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Lex.TEntry", padding=8, fieldbackground="#FFFFFF", bordercolor="#CBD5D3", font=("Malgun Gothic", 11))
        style.configure("Lex.TSpinbox", padding=7, fieldbackground="#FFFFFF", background="#FFFFFF", bordercolor="#CBD5D3", arrowcolor="#193D43", font=("Malgun Gothic", 11))
        style.configure("Lex.TCombobox", padding=7, fieldbackground="#FFFFFF", background="#FFFFFF", bordercolor="#CBD5D3", font=("Malgun Gothic", 10))
        style.configure("Primary.TButton", padding=(18, 11), background="#193D43", foreground="#FFFFFF", borderwidth=0, font=("Malgun Gothic", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#28545A"), ("disabled", "#A8B5B5")])
        style.configure("Quiet.TButton", padding=(14, 9), background="#EAF0EE", foreground="#193D43", borderwidth=0, font=("Malgun Gothic", 10, "bold"))
        style.map("Quiet.TButton", background=[("active", "#D9E6E1"), ("disabled", "#F1F3F2")])

        hero = tk.Frame(root, bg="#193D43", height=134)
        hero.pack(fill="x")
        hero.pack_propagate(False)
        tk.Label(hero, text="LEXICON  /  WORKSHEET STUDIO", bg="#193D43", fg="#C5A875", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=30, pady=(20, 5))
        tk.Label(hero, text="영영 풀이 문제 생성기", bg="#193D43", fg="#FFFFFF", font=("Malgun Gothic", 23, "bold")).pack(anchor="w", padx=30)
        tk.Label(hero, text="단어장을 선택하고, 문제를 검토한 뒤 PDF로 저장하세요.", bg="#193D43", fg="#D4E0DE", font=("Malgun Gothic", 10)).pack(anchor="w", padx=31, pady=(5, 0))

        body = tk.Frame(root, bg="#F3F5F4", padx=22, pady=20)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg="#FFFFFF", width=322, padx=22, pady=18, highlightbackground="#E0E7E4", highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 16))
        left.pack_propagate(False)
        right = tk.Frame(body, bg="#FFFFFF", padx=22, pady=18, highlightbackground="#E0E7E4", highlightthickness=1)
        right.pack(side="left", fill="both", expand=True)

        self.section(left, "01  단어장", "PDF 또는 CSV 파일을 불러옵니다")
        sources = tk.Frame(left, bg="#FFFFFF")
        sources.pack(fill="x", pady=(4, 10))
        sources.grid_columnconfigure(0, weight=1)
        sources.grid_columnconfigure(1, weight=1)
        ttk.Button(sources, text="다른 단어장 열기", style="Quiet.TButton", command=self.open_file).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.builtin_button = ttk.Button(sources, text="어휘끝 (내장)", style="Quiet.TButton", command=self.load_builtin)
        self.builtin_button.grid(row=0, column=1, sticky="ew")
        tk.Label(left, textvariable=self.file_label, bg="#FFFFFF", fg="#193D43", font=("Malgun Gothic", 10, "bold"), wraplength=270, justify="left").pack(anchor="w")
        tk.Label(left, textvariable=self.source_label, bg="#FFFFFF", fg="#71817F", font=("Malgun Gothic", 9), wraplength=270, justify="left").pack(anchor="w", pady=(5, 0))
        tk.Frame(left, bg="#E4EAE8", height=1).pack(fill="x", pady=14)

        self.section(left, "02  출제 조건", "문제 유형, 범위와 문항 수를 정하세요")
        choice = tk.Frame(left, bg="#FFFFFF")
        choice.pack(fill="x", pady=(0, 4))
        choice.grid_columnconfigure(0, weight=3)
        choice.grid_columnconfigure(1, weight=2)
        for column, (label, variable, values) in enumerate((
            ("문제 유형", self.mode, tuple(MODES)),
            ("난이도", self.level, ("전체", "쉬움 (1)", "보통 (2)", "어려움 (3)")),
        )):
            cell = tk.Frame(choice, bg="#FFFFFF")
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 8) if column == 0 else 0)
            tk.Label(cell, text=label, bg="#FFFFFF", fg="#667673", font=("Malgun Gothic", 9)).pack(anchor="w", pady=(0, 5))
            ttk.Combobox(cell, textvariable=variable, values=values, style="Lex.TCombobox", state="readonly", width=8).pack(fill="x")
        grid = tk.Frame(left, bg="#FFFFFF")
        grid.pack(fill="x", pady=(5, 12))
        for column, (label, variable) in enumerate((("시작 단원", self.first), ("끝 단원", self.last), ("문제 수", self.count))):
            cell = tk.Frame(grid, bg="#FFFFFF")
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 8) if column < 2 else 0)
            grid.grid_columnconfigure(column, weight=1)
            tk.Label(cell, text=label, bg="#FFFFFF", fg="#667673", font=("Malgun Gothic", 9)).pack(anchor="w", pady=(0, 5))
            if column < 2:
                ttk.Entry(cell, textvariable=variable, style="Lex.TEntry", width=6).pack(fill="x")
            else:
                self.count_box = ttk.Spinbox(cell, textvariable=variable, from_=1, to=1, increment=1, style="Lex.TSpinbox", width=6, command=self.clamp_count)
                self.count_box.pack(fill="x")
        self.limit_label = tk.Label(left, textvariable=self.limit_text, bg="#FFFFFF", fg="#71817F", font=("Malgun Gothic", 9), wraplength=270, justify="left")
        self.limit_label.pack(anchor="w", pady=(0, 4))
        self.generate_button = ttk.Button(left, text="문제 만들기  →", style="Primary.TButton", command=self.generate)
        self.generate_button.pack(fill="x", pady=(12, 10))
        self.status = tk.Label(left, text="예제 단어장을 불러오는 중입니다.", bg="#FFFFFF", fg="#667673", font=("Malgun Gothic", 9), wraplength=270, justify="left")
        self.status.pack(anchor="w")

        top = tk.Frame(right, bg="#FFFFFF")
        top.pack(fill="x", pady=(0, 12))
        tk.Label(top, text="문제 미리보기", bg="#FFFFFF", fg="#193D43", font=("Malgun Gothic", 16, "bold")).pack(side="left")
        self.review_button = ttk.Button(top, text="정답 검토", style="Quiet.TButton", command=self.open_review, state="disabled")
        self.review_button.pack(side="right")
        tk.Label(right, text="보기의 연결과 정답을 확인한 뒤 PDF로 저장합니다.", bg="#FFFFFF", fg="#71817F", font=("Malgun Gothic", 9)).pack(anchor="w", pady=(0, 12))
        footer = tk.Frame(right, bg="#FFFFFF")
        footer.pack(side="bottom", fill="x", pady=(13, 0))
        tk.Label(footer, textvariable=self.review_label, bg="#FFFFFF", fg="#71817F", font=("Malgun Gothic", 9)).pack(side="left")
        self.save_key_button = ttk.Button(footer, text="정답지 PDF", style="Quiet.TButton", command=lambda: self.save(True), state="disabled")
        self.save_key_button.pack(side="right")
        self.save_exam_button = ttk.Button(footer, text="시험지 PDF", style="Primary.TButton", command=lambda: self.save(False), state="disabled")
        self.save_exam_button.pack(side="right", padx=(0, 8))
        preview = tk.Frame(right, bg="#FAFBFA", highlightbackground="#E3EAE7", highlightthickness=1)
        preview.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(preview)
        scroll.pack(side="right", fill="y")
        self.output = tk.Text(preview, wrap="word", font=("Malgun Gothic", 10), bg="#FAFBFA", fg="#263D3D", relief="flat", padx=18, pady=16, spacing2=3, spacing3=5, state="disabled", yscrollcommand=scroll.set)
        self.output.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.output.yview)
        # 어휘끝 수능편이 내장되어 있어 켜자마자 바로 출제할 수 있다. 없으면 예제 단어장을 연다.
        if BUILTIN_PATH.exists():
            self.load_builtin()
        elif (BASE / "예제_단어장.csv").exists():
            self.load(BASE / "예제_단어장.csv")

    def section(self, parent, title, subtitle):
        tk.Label(parent, text=title, bg="#FFFFFF", fg="#193D43", font=("Malgun Gothic", 12, "bold")).pack(anchor="w")
        tk.Label(parent, text=subtitle, bg="#FFFFFF", fg="#71817F", font=("Malgun Gothic", 9)).pack(anchor="w", pady=(4, 12))

    def load_builtin(self):
        self.load(BUILTIN_PATH, "어휘끝 수능편 (내장)")

    def load(self, path, name=None):
        try:
            rows = read_words(path)
            if not rows:
                raise ValueError("읽을 수 있는 단어가 없습니다.")
        except Exception as exc:
            messagebox.showerror("단어장 오류", str(exc))
            return
        self.rows = rows
        if self.review_window is not None and self.review_window.winfo_exists():
            self.review_window.destroy()
            self.review_window = None
        self.resolved_rows = []
        self.questions = []
        self.reviewed = []
        self.review_button.config(state="disabled")
        self.save_exam_button.config(state="disabled")
        self.save_key_button.config(state="disabled")
        self.review_label.set("문제를 만든 뒤 검토해 주세요")
        self.file_label.set(f"{name or Path(path).name} ({len(rows)}개)")
        days = sorted({row[0] for row in rows})
        self.first.set(str(days[0]))
        self.last.set(str(days[-1]))
        missing = sum(not row[2] for row in rows)
        korean = sum(bool(row[4]) for row in rows)
        self.source_label.set(f"단원 {days[0]}–{days[-1]} · {len(rows)}개 단어 · 한국어 뜻 {korean}개 · 영영 풀이 {len(rows) - missing}개")
        if not missing:
            note = "세 가지 문제 유형을 모두 만들 수 있습니다."
        elif korean:
            note = "어휘끝이 아닌 단어장이라 영영 풀이가 없어, 빈칸 문제(영어 → 한국어, 한국어 → 영어)만 만들 수 있습니다."
            if self.current_mode() == MATCH:
                self.mode.set("영어 → 한국어 뜻 쓰기")
        else:
            note = "영영 풀이와 한국어 뜻을 모두 찾지 못해 문제를 만들 수 없습니다. 표제어 옆에 한글 뜻이 있는 단어장인지 확인하세요."
        self.status.config(text=f"단원 {days[0]}~{days[-1]}, 단어 {len(rows)}개. {note}")
        self.refresh_limit()
        self.display("단어장을 불러왔습니다. 문제 유형을 고르고 '문제 만들기'를 누르세요.\n\n· 영영 풀이 연결: 다섯 쌍 중 틀린 연결 고르기\n· 영어 → 한국어 뜻 쓰기: 영단어를 보고 뜻 쓰기\n· 한국어 → 영어 단어 쓰기: 뜻을 보고 영단어 쓰기")

    def current_mode(self):
        return MODES.get(self.mode.get(), MATCH)

    def current_level(self):
        return {"전체": 0, "쉬움 (1)": 1, "보통 (2)": 2, "어려움 (3)": 3}.get(self.level.get(), 0)

    def refresh_limit(self):
        """단원 범위·난이도가 바뀔 때마다 최대 문항 수를 다시 계산해 보여주고 입력 상한에 건다."""
        if not hasattr(self, "count_box"):
            return
        try:
            first_day, last_day = int(self.first.get()), int(self.last.get())
        except ValueError:
            self.limit = 0
            self.limit_text.set("시작 단원과 끝 단원을 숫자로 입력하세요.")
            self.count_box.config(to=1)
            return
        if not self.rows:
            return
        if first_day > last_day:
            self.limit = 0
            self.limit_text.set("시작 단원이 끝 단원보다 큽니다.")
            self.count_box.config(to=1)
            return
        mode = self.current_mode()
        self.limit = max_questions(self.rows, first_day, last_day, self.current_level(), mode)
        self.count_box.config(to=max(1, self.limit))
        missing = missing_definitions(self.rows, first_day, last_day, self.current_level()) if mode == MATCH else 0
        if missing:
            self.limit_text.set(f"이 범위의 {missing}개 단어에 영영 풀이가 없어 영영 풀이 문제를 만들 수 없습니다. 영영 풀이 문제는 어휘끝 단어만 됩니다. 빈칸 문제 유형을 고르세요.")
        elif self.limit < 1 and mode != MATCH:
            self.limit_text.set("이 범위에는 한국어 뜻이 있는 단어가 없습니다. 빈칸 문제는 한국어 뜻이 든 단어장에서만 만들 수 있습니다.")
        elif self.limit < 1:
            self.limit_text.set("이 범위에는 단어가 모자랍니다. 한 문제에 중복 없는 단어 5개가 필요합니다.")
        else:
            self.limit_text.set(f"최대 {self.limit}문제까지 만들 수 있습니다.")
        self.clamp_count()

    def clamp_count(self):
        """상한을 넘겨 입력하면 그 자리에서 상한으로 되돌린다."""
        if not hasattr(self, "count_box") or self.limit < 1:
            return
        text = self.count.get().strip()
        if not text.isdigit():
            return
        value = int(text)
        if value > self.limit:
            self.count.set(str(self.limit))
        elif value < 1:
            self.count.set("1")

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("단어장", "*.csv *.pdf"), ("모든 파일", "*.*")])
        if path:
            self.load(path)

    def display(self, text):
        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.config(state="disabled")

    def generate(self):
        try:
            if self.review_window and self.review_window.winfo_exists():
                self.review_window.destroy()
                self.review_window = None
            level = {"전체": 0, "쉬움 (1)": 1, "보통 (2)": 2, "어려움 (3)": 3}[self.level.get()]
            first_day, last_day, count = int(self.first.get()), int(self.last.get()), int(self.count.get())
            if first_day > last_day or count < 1:
                raise ValueError("단원 범위와 문제 수를 확인하세요.")
            mode = self.current_mode()
            if mode != MATCH:
                self.question_mode = mode
                self.questions = make_blank_questions(self.rows, first_day, last_day, level, count)
                self.show_questions()
                return
            missing = missing_definitions(self.rows, first_day, last_day, level)
            if missing:
                raise ValueError(f"이 범위의 {missing}개 단어에 영영 풀이가 없습니다. 영영 풀이 문제는 어휘끝 단어로만 만들 수 있으니, 빈칸 문제 유형을 고르세요.")
            limit = max_questions(self.rows, first_day, last_day, level)
            if limit < 1:
                raise ValueError("이 범위에는 중복 없는 단어가 5개도 되지 않습니다. 단원 범위를 넓히거나 난이도를 '전체'로 바꾸세요.")
            if count > limit:
                raise ValueError(f"이 범위에서는 최대 {limit}문제까지 만들 수 있습니다. 문제 수를 {limit} 이하로 입력하세요.")
            selected = [row for row in self.rows if first_day <= row[0] <= last_day and (level == 0 or level == row[3])]
            self.question_mode = MATCH
            self.resolved_rows = selected
            self.questions = make_questions(selected, first_day, last_day, level, count)
            self.show_questions()
        except (ValueError, KeyError) as exc:
            messagebox.showerror("문제 생성 오류", str(exc))

    def show_questions(self):
        if self.question_mode != MATCH:
            # 빈칸 문제는 정답이 교재 뜻 그대로라 검토 단계 없이 바로 저장한다.
            self.reviewed = [True] * len(self.questions)
            self.review_button.config(state="disabled")
            self.update_review_status()
            self.display(format_exam(self.questions, show_answers=True, mode=self.question_mode))
            self.status.config(text=f"중복 단어 없이 {len(self.questions)}문제를 만들었습니다. 미리보기의 괄호 안이 정답입니다. 바로 PDF로 저장할 수 있습니다.")
            return
        self.reviewed = [False] * len(self.questions)
        self.review_button.config(state="normal")
        self.update_review_status()
        self.display(format_exam(self.questions))
        self.status.config(text=f"중복 단어 없이 {len(self.questions)}문제를 만들었습니다. 오른쪽의 '정답 검토'에서 확인하세요.")

    def update_review_status(self):
        complete = sum(self.reviewed)
        total = len(self.reviewed)
        self.review_label.set(f"검토 {complete}/{total} 완료" if total else "문제를 만든 뒤 검토해 주세요")
        state = "normal" if total and complete == total else "disabled"
        self.save_exam_button.config(state=state)
        self.save_key_button.config(state=state)

    def open_review(self):
        if not self.questions:
            return
        if self.review_window and self.review_window.winfo_exists():
            self.review_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.review_window = window
        window.title("LEXICON | 문제 검토")
        window.geometry("1050x720")
        window.minsize(850, 560)
        window.configure(bg="#F3F5F4")
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", lambda: (window.destroy(), setattr(self, "review_window", None)))
        header = tk.Frame(window, bg="#193D43", padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="정답 검토", bg="#193D43", fg="#FFFFFF", font=("Malgun Gothic", 17, "bold")).pack(anchor="w")
        tk.Label(header, text="오답으로 지정된 보기와 원래 뜻을 비교해 주세요. 확인한 문제만 PDF에 넣습니다.", bg="#193D43", fg="#D4E0DE", font=("Malgun Gothic", 10)).pack(anchor="w", pady=(5, 0))
        body = tk.Frame(window, bg="#F3F5F4", padx=18, pady=18)
        body.pack(fill="both", expand=True)
        navigation = tk.Frame(body, bg="#FFFFFF", width=190, padx=14, pady=14)
        navigation.pack(side="left", fill="y", padx=(0, 14))
        navigation.pack_propagate(False)
        tk.Label(navigation, text="문항", bg="#FFFFFF", fg="#193D43", font=("Malgun Gothic", 11, "bold")).pack(anchor="w", pady=(0, 9))
        self.review_list = tk.Listbox(navigation, borderwidth=0, highlightthickness=0, activestyle="none", bg="#FFFFFF", fg="#263D3D", selectbackground="#DCEAE6", selectforeground="#193D43", font=("Malgun Gothic", 11))
        self.review_list.pack(fill="both", expand=True)
        self.review_list.bind("<<ListboxSelect>>", self.render_review)
        details = tk.Frame(body, bg="#FFFFFF", padx=20, pady=18)
        details.pack(side="left", fill="both", expand=True)
        tk.Label(details, text="보기와 정답", bg="#FFFFFF", fg="#193D43", font=("Malgun Gothic", 13, "bold")).pack(anchor="w", pady=(0, 9))
        actions = tk.Frame(details, bg="#FFFFFF")
        actions.pack(side="bottom", fill="x", pady=(13, 0))
        ttk.Button(actions, text="이 문제 다시 뽑기", style="Quiet.TButton", command=self.reroll_review).pack(side="left")
        ttk.Button(actions, text="검토 완료", style="Primary.TButton", command=self.mark_reviewed).pack(side="right")
        text_frame = tk.Frame(details, bg="#FAFBFA")
        text_frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(text_frame)
        scroll.pack(side="right", fill="y")
        self.review_text = tk.Text(text_frame, wrap="word", bg="#FAFBFA", fg="#263D3D", font=("Malgun Gothic", 10), relief="flat", padx=15, pady=14, spacing3=5, state="disabled", yscrollcommand=scroll.set)
        self.review_text.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.review_text.yview)
        self.refresh_review_list()
        self.review_list.selection_set(0)
        self.render_review()

    def review_index(self):
        selection = self.review_list.curselection()
        return selection[0] if selection else None

    def refresh_review_list(self):
        selected = self.review_index()
        self.review_list.delete(0, "end")
        for index, checked in enumerate(self.reviewed, 1):
            self.review_list.insert("end", f"{'✓' if checked else '○'}  {index:02d}번 문제")
        if selected is not None:
            self.review_list.selection_set(selected)

    def render_review(self, event=None):
        index = self.review_index()
        if index is None:
            return
        options, answer, word, correct_definition = self.questions[index]
        wrong_definition = options[answer - 1][1]
        score = decoy_score(word, correct_definition, wrong_definition)
        confidence = "품사가 달라 비교적 명확한 오답 후보" if score[0] == 0 else "뜻이 겹칠 수 있으므로 정답 유일성 확인 필요"
        lines = [f"{index + 1}번 문제", ""]
        lines.extend(f"{'→' if number == answer else ' '} {number}) {option_word} : {definition}" for number, (option_word, definition) in enumerate(options, 1))
        lines.extend(["", f"오답으로 지정: {answer}번  {word}", f"원래 맞는 풀이: {correct_definition}", "", confidence])
        self.review_text.config(state="normal")
        self.review_text.delete("1.0", "end")
        self.review_text.insert("1.0", "\n".join(lines))
        self.review_text.config(state="disabled")
        self.review_text.yview_moveto(0)

    def mark_reviewed(self):
        index = self.review_index()
        if index is None:
            return
        self.reviewed[index] = True
        self.refresh_review_list()
        self.update_review_status()
        next_index = next((i for i, checked in enumerate(self.reviewed) if not checked), None)
        if next_index is not None:
            self.review_list.selection_clear(0, "end")
            self.review_list.selection_set(next_index)
            self.review_list.see(next_index)
            self.render_review()
        else:
            self.status.config(text="모든 문제 검토가 끝났습니다. 시험지와 정답지 PDF를 저장할 수 있습니다.")

    def reroll_review(self):
        index = self.review_index()
        if index is None:
            return
        options, answer, word, _ = self.questions[index]
        pool = [(day, entry, definition) for day, entry, definition, _, _ in self.resolved_rows]
        by_word = {item[1].casefold(): item for item in pool}
        choices = [by_word[entry.casefold()] for entry, _ in options]
        visible_words = {entry.casefold() for question, _, _, _ in self.questions for entry, _ in question}
        used_decoys = {question[answer_index - 1][1] for question, answer_index, _, _ in self.questions if question is not options}
        extras = [item for item in pool if item[1].casefold() not in visible_words and item[2] not in used_decoys]
        try:
            self.questions[index] = make_one_question(choices + extras if extras else pool, choices, avoid=(word, options[answer - 1][1]))
        except ValueError as exc:
            messagebox.showerror("문제 교체 오류", str(exc), parent=self.review_window)
            return
        self.reviewed[index] = False
        self.refresh_review_list()
        self.update_review_status()
        self.display(format_exam(self.questions))
        self.render_review()

    def save(self, answers):
        if not self.questions:
            messagebox.showinfo("안내", "먼저 문제를 만드세요.")
            return
        if not all(self.reviewed):
            messagebox.showinfo("검토 필요", "모든 문제를 검토한 뒤 PDF로 저장하세요.")
            return
        title = MODE_TITLES[self.question_mode][0]
        name = f"{title}_정답지.pdf" if answers else f"{title}_시험지.pdf"
        path = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=name, filetypes=[("PDF 파일", "*.pdf")])
        if path:
            try:
                save_pdf(path, self.questions, answers, self.question_mode)
            except Exception as exc:
                messagebox.showerror("PDF 저장 오류", str(exc))
                return
            self.status.config(text=f"저장했습니다: {path}")


def self_test():
    rows = read_words(BASE / "예제_단어장.csv")
    questions = make_questions(rows, 1, 5, 2, 6, random.Random(7))
    assert len(questions) == 6
    all_words = [word for options, _, _, _ in questions for word, _ in options]
    assert len(all_words) == len(set(all_words)) == 30
    for options, answer, word, definition in questions:
        assert len(options) == 5 and len({item[0] for item in options}) == 5
        assert options[answer - 1][0] == word
        assert options[answer - 1][1] != definition
        assert sum((w, d) not in {(x[1], x[2]) for x in rows} for w, d in options) == 1
    try:
        make_questions(rows, 1, 5, 2, 7, random.Random(7))
    except ValueError:
        pass
    else:
        raise AssertionError("중복 단어가 필요한 문제 수를 허용했습니다.")

    # 표제어 글자 크기 판별 — 어휘끝 수능편의 실제 분포(본문 7.0 / 표제어 9.9 / 쪽번호 8.0 / 단원 20.0)
    assert _headword_size({7.0: 8534, 9.9: 1647, 8.0: 151, 20.0: 53}, {9.9: 1573, 7.0: 3066}) == 9.9
    assert _headword_size({7.0: 100}, {7.0: 90}) == 0
    assert _headword_size({}, {}) == 0
    assert SECTION_RE.fullmatch("Unit 01").group(1) == "01"
    assert SECTION_RE.fullmatch("DAY 7").group(1) == "7"
    assert SECTION_RE.fullmatch("표지") is None

    limit = max_questions(rows, 1, 5, 2)
    assert limit == 6, limit
    assert max_questions(rows, 1, 1, 2) == 1
    assert max_questions(rows, 1, 5, 3) == 0
    assert len(make_questions(rows, 1, 5, 2, limit, random.Random(3))) == limit
    try:
        make_questions(rows, 1, 5, 2, limit + 1, random.Random(3))
    except ValueError:
        pass
    else:
        raise AssertionError("최대 문항 수를 넘긴 요청이 통과했습니다.")

    # 빈칸 문제: 한 문제에 단어 하나, 단어·뜻 중복 없음
    assert max_questions(rows, 1, 5, 2, EN_TO_KO) == 30
    blanks = make_blank_questions(rows, 1, 5, 2, 12, random.Random(1))
    assert len(blanks) == 12 and len({word for word, _ in blanks}) == 12 and all(korean for _, korean in blanks)
    assert "( 성취하다, 이루다 )" in format_exam([("achieve", "성취하다, 이루다")], True, EN_TO_KO)
    assert "( achieve )" in format_exam([("achieve", "성취하다, 이루다")], True, KO_TO_EN)
    try:
        make_blank_questions(rows, 1, 5, 2, 31)
    except ValueError:
        pass
    else:
        raise AssertionError("빈칸 문제 상한을 넘긴 요청이 통과했습니다.")

    # 표제어 읽기: 두 줄로 찍힌 'medieval/mediaev' + 'al', 조각난 한글 뜻, 뜻 없는 부록 제목
    def span(text, size, y):
        return {"text": text, "size": size, "bbox": (0, y, 10, y + 8)}
    pages = [(20, [
        span("medieval/mediaev", 9.9, 473), span("al", 9.9, 489), span("중세의; 중세풍의", 7.0, 463), span("This church", 7.0, 482),
        span("swell", 9.9, 61), span("붓다,", 7.0, 41), span(" 부풀다; 증가하다", 7.0, 41), span("My arm", 7.0, 62),
    ] + [span(f"word{chr(97 + i)}", 9.9, 100 + i) for i in range(3)] + [span("뜻", 7.0, 90)]),
        (53, [span("Inspirational Quotes", 9.9, 71), span(" Interviewer: Did you", 7.0, 124)])]
    pages[0][1][8:11] = [item for i in range(3) for item in (span(f"word{'abc'[i]}", 9.9, 100 + i * 20), span("뜻", 7.0, 95 + i * 20))]
    heads = _sized_headwords(pages, 9.9)
    words = [item[1] for item in heads]
    assert words[:2] == ["medieval", "swell"] and "Inspirational Quotes" not in words and "al" not in words, words
    assert heads[0][4] == "중세의; 중세풍의" and heads[1][4] == "붓다, 부풀다; 증가하다", heads[:2]

    # 다른 단어장(영영 풀이 없음, 한국어 뜻 있음): 빈칸 문제만 된다.
    other = [(1, f"zzword{i}", "", 2, f"뜻{i}") for i in range(12)]
    assert max_questions(other, 1, 1, 0) == 0 and missing_definitions(other, 1, 1, 0) == 12
    assert max_questions(other, 1, 1, 0, EN_TO_KO) == 12

    # 내장 영영 풀이(어휘끝 수능편)
    builtin = builtin_definitions()
    assert len(builtin) >= 1577 and "medieval" in builtin and "al" not in builtin
    print("self-test OK")


def smoke_gui():
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    # 켜자마자 어휘끝 수능편(내장)이 열린다.
    assert app.file_label.get().startswith("어휘끝 수능편 (내장) (1577개)"), app.file_label.get()
    assert (app.first.get(), app.last.get()) == ("1", "53") and app.limit >= 300, (app.first.get(), app.last.get(), app.limit)
    app.load(BASE / "예제_단어장.csv")
    assert app.limit == 6, app.limit
    assert "최대 6문제" in app.limit_text.get(), app.limit_text.get()
    app.count.set("99")
    root.update_idletasks()
    assert app.count.get() == "6", app.count.get()
    assert app.count_box.cget("to") in (6, 6.0, "6"), app.count_box.cget("to")
    app.last.set("1")
    root.update_idletasks()
    assert app.limit == 1 and app.count.get() == "1", (app.limit, app.count.get())
    app.last.set("5")
    root.update_idletasks()
    app.count.set("5")
    app.generate()
    assert len(app.questions) == 5
    assert app.save_exam_button.instate(["disabled"])
    app.open_review()
    before = app.questions[0]
    app.reroll_review()
    assert app.questions[0] != before
    assert app.save_exam_button.instate(["disabled"])
    for _ in app.questions:
        app.mark_reviewed()
    assert all(app.reviewed)
    assert not app.save_exam_button.instate(["disabled"])
    all_words = [word for options, _, _, _ in app.questions for word, _ in options]
    assert len(all_words) == len(set(all_words))
    with tempfile.TemporaryDirectory() as folder:
        exam = Path(folder) / "exam.pdf"
        key = Path(folder) / "key.pdf"
        save_pdf(exam, app.questions)
        save_pdf(key, app.questions, answers=True)
        with fitz.open(exam) as pdf:
            text = pdf[0].get_text()
            assert "01" in text and CIRCLED[0] in text
        with fitz.open(key) as pdf:
            text = pdf[0].get_text()
            assert "정답 일람" in text and "해설" in text

        # 빈칸 문제 두 방향: 검토 없이 바로 저장, 정답지에는 정답이 적힌다.
        for label, mode in (("영어 → 한국어 뜻 쓰기", EN_TO_KO), ("한국어 → 영어 단어 쓰기", KO_TO_EN)):
            app.mode.set(label)
            root.update_idletasks()
            assert app.limit == 30, app.limit
            app.count.set("30")
            app.generate()
            assert app.question_mode == mode and len(app.questions) == 30 and all(app.reviewed)
            assert not app.save_exam_button.instate(["disabled"])
            exam = Path(folder) / f"{mode}_exam.pdf"
            key = Path(folder) / f"{mode}_key.pdf"
            save_pdf(exam, app.questions, False, mode)
            save_pdf(key, app.questions, True, mode)
            # 글자를 낱말 단위로 찍어 추출 텍스트에는 낱말 사이 공백이 빠질 수 있으므로 공백을 지우고 비교한다.
            word, korean = app.questions[0]
            meaning = re.sub(r"\s+", "", korean.split(",")[0])
            with fitz.open(exam) as pdf:
                text = re.sub(r"\s+", "", "".join(page.get_text() for page in pdf))
                assert (word if mode == EN_TO_KO else meaning) in text
                assert (meaning if mode == EN_TO_KO else word) not in text
            with fitz.open(key) as pdf:
                text = re.sub(r"\s+", "", "".join(page.get_text() for page in pdf))
                assert word in text and meaning in text and "정답지" in text
    root.destroy()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--smoke-gui" in sys.argv:
        smoke_gui()
    else:
        window = tk.Tk()
        App(window)
        window.mainloop()
