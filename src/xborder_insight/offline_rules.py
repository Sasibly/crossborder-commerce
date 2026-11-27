"""Versioned offline V2. Clause-local evidence; no sample IDs or dataset lookups."""
import asyncio
import hashlib
import json
from pathlib import Path
import re

from .llm import LLMResponse, _field
from .taxonomy import LABEL_HINTS, NEGATIVE_CUES, POSITIVE_CUES

RULE_VERSION = 'offline-v2-' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]

# Aspect terms are independent of sentiment. Mentioning a pump is not a failed pump.
PATTERNS = {
    'cleaning': r'清洗|清理|清洁|拆洗|难洗|拆开.{0,12}洗|hard to clean|easy to clean|clean(?:ing)?|slime|mold',
    'noise': r'噪[音声]|异响|吵|安静|静音|嗡|轰|泵声|水泵声|声音.{0,8}(?:大|小|响)|nois[ey]|loud|buzz|rattl|quiet|silent',
    'leakage': r'漏水|漏液|渗水|渗漏|leak|spill',
    'pump_life': r'(?:泵|马达|pump|motor).{0,30}(?:坏|失灵|报废|烧毁|寿命|不(?:再)?(?:出水|工作)|停[止了]|died|dead|stopped working|fail)',
    'charging_speed': r'(?:充电|出水|水流|流量).{0,15}(?:慢|小|少|弱|低)|(?:slow|takes forever).{0,20}(?:charg|flow)|trickle',
}
FAILURE = r'漏水|漏液|渗水|渗漏|吵|噪音|噪声|异响|坏|失灵|不出水|hard to clean|noisy|loud|leak'
NEGATED = r'(?:没有|并无|未|不曾|没|不)(?:再|发现|出现|发生|觉得|感觉|任何|明显|一点|那么|很|太|曾经)*\s*(?:' + FAILURE + ')'


def clauses(text):
    """Keep exact source substrings, including offsets for attribution corrections."""
    return [(m.start(), m.end(), m.group().strip()) for m in
            re.finditer(r'[^，,。.!！？?;；\n]+', text) if m.group().strip()]


def sentiment(text, label, rating):
    low = text.lower()
    # Quoted/uncertain experience is not a confirmed first-person negative report.
    if re.search(r'听说|据说|别人说|朋友说|不确定|无法确定|hear(?:d)? that|reportedly', low):
        return 'neutral'
    if re.search(r'(?:不能|不算|并非|谈不上).{0,4}(?:安静|静音|方便|容易|好用)|(?:not|never)\s+(?:quiet|silent|easy)', low):
        return 'negative'
    if re.search(r'(?:没|不).{0,8}才怪|根本不能|完全不能', low):
        return 'negative'
    # Adjacent negation excludes temporal phrases such as 没多久就坏/漏水.
    cleaned = re.sub(NEGATED, '', low)
    cleaned = re.sub(r'\b(?:no|not|never|does not|doesn\x27t)\s+(?:leak\w*|noisy|loud|hard to clean)\b', '', cleaned)
    has_negated_failure = cleaned != low
    negatives = list(NEGATIVE_CUES) + ['died', 'dead', '失灵', '费劲', '费力', '麻烦', '困难', '异响', '渗水', '漏液']
    if any(cue in cleaned for cue in negatives):
        return 'negative'
    if has_negated_failure:
        return 'positive'
    if label == 'charging_speed' and re.search(PATTERNS['charging_speed'], low, re.I):
        return 'negative'
    if label == 'noise' and re.search(r'安静|静音|quiet|silent', low):
        return 'positive'
    if label == 'noise' and re.search(r'噪[音声]|异响|嗡|轰|吵|noisy|loud|buzz|rattl', low):
        return 'negative'
    if label == 'cleaning' and re.search(r'方便|容易|轻松|省事|easy|simple', low):
        return 'positive'
    if any(cue in low for cue in POSITIVE_CUES):
        return 'positive'
    return 'negative' if rating <= 2 else 'positive' if rating >= 4 else 'neutral'


def extract_points(body, title='', rating=3):
    text = body or title
    segments = []
    # Split contrast/conjunctions without fabricating excerpts.
    for start, end, clause in clauses(text):
        for piece in re.split(r'但是|不过|然而|可是|只是|(?<!不)但|\bbut\b|\bthough\b|\byet\b', clause, flags=re.I):
            if piece.strip():
                segments.append(piece.strip())
    points = []
    for label, hints in LABEL_HINTS.items():
        pattern = PATTERNS.get(label)
        candidates = [s for s in segments if (re.search(pattern, s, re.I) if pattern else any(h in s.lower() for h in hints))]
        if not candidates and title and title != text:
            if re.search(pattern, title, re.I) if pattern else any(h in title.lower() for h in hints):
                candidates = [title]
        if not candidates:
            continue
        # A short adjacent evaluation with no new subject can qualify the same aspect.
        expanded = []
        for candidate in candidates:
            if candidate not in segments:
                expanded.append(candidate)
                continue
            index = segments.index(candidate)
            if index + 1 < len(segments):
                following = segments[index + 1]
                has_new_aspect = any(re.search(p, following, re.I) for p in PATTERNS.values())
                has_new_subject = re.search(r'客服|物流|说明书|外观|价格|耗材|滤芯|安装|容量', following)
                has_evaluation = re.search(r'方便|麻烦|困难|容易|费劲|费力|easy|hard', following, re.I)
                start = text.find(candidate); next_start = text.find(following, start + len(candidate))
                between = text[start + len(candidate):next_start]
                if (not has_new_aspect and not has_new_subject and has_evaluation and len(following) <= 40
                        and start >= 0 and next_start >= 0 and not re.search(r'[。.!！？?;；\n]', between)):
                    candidate = text[start:next_start + len(following)]
            expanded.append(candidate)
        candidates = expanded
        # Double negation of a failed pump does not establish shortened service life.
        if label == 'pump_life':
            candidates = [s for s in candidates if not re.search(r'不是不|并非不', s)]
            if not candidates:
                continue
        attributed = None
        if label == 'leakage':
            # A suspicion corrected to a spilled cup/pet splash is not product leakage.
            match = re.search(r'(?:以为|怀疑)[^。.!！？?\n]*(?:漏水|渗水)[^。.!！？?\n]*?(?:后来|结果|原来|其实)[^。.!！？?\n]*(?:杯|猫|狗|宠物)[^。.!！？?\n]*(?:倒|打翻|拨|泼|洒)', text)
            if match:
                attributed = match.group()
        if attributed is not None:
            chosen, polarity = attributed, 'neutral'
        else:
            # Prefer direct experience over hearsay, then retain explicit negative aspects.
            direct = [s for s in candidates if not re.search(r'听说|据说|别人说|朋友说|reportedly|heard that', s, re.I)]
            pool = direct or candidates
            chosen = min(pool, key=lambda s: {'negative': 0, 'neutral': 1, 'positive': 2}[sentiment(s, label, rating)])
            polarity = sentiment(chosen, label, rating)
        # Preserve a literal window around the aspect when a clause is unusually long.
        if len(chosen) > 240:
            match = re.search(pattern, chosen, re.I) if pattern else None
            offset = max(0, match.start() - 50) if match else 0
            chosen = chosen[offset:offset + 240]
        points.append({'label': label, 'polarity': polarity, 'evidence': chosen, 'confidence': .7})
    points.sort(key=lambda p: ({'negative': 0, 'neutral': 1, 'positive': 2}[p['polarity']], list(LABEL_HINTS).index(p['label'])))
    return points[:3]


class OfflineRuleClient:
    name = 'offline-rules-v2'
    rule_version = RULE_VERSION

    async def complete(self, system, user):
        identity = _field(user, 'REVIEW_ID') or 'unknown'
        rating_raw = _field(user, 'RATING') or '3'
        rating = int(rating_raw) if rating_raw.isdigit() else 3
        body = user.split('\nBODY: ', 1)[-1].split('\n\n上一次输出', 1)[0]
        title_match = re.search(r'^TITLE:[ \t]*(.*)$', user, re.M)
        title = title_match.group(1) if title_match else ''
        points = extract_points(body, title, rating)
        await asyncio.sleep(.01)
        content = json.dumps({'review_id': identity, 'is_relevant': bool(points), 'points': points}, ensure_ascii=False)
        return LLMResponse(content, max(1, len(user) // 4), max(1, len(content) // 4), 10)

    async def aclose(self):
        return None
