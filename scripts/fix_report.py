"""Record repair progress without replacing the original independent evidence."""
from pathlib import Path
import re

PATH = Path(__file__).resolve().parents[1] / 'docs/qa/BUG_REPORT.md'

def update(number, status, details):
    text = PATH.read_text(encoding='utf-8')
    code = f'BUG-{number:03d}'
    text = re.sub(rf'(\| {code} \|[^\n]*\| )[^|\n]+(\|)', rf'\g<1>{status} \2', text)
    start = text.index('### ' + code + '：')
    end = text.find('\n### ', start + 1)
    if end < 0: end = text.index('\n## 5.', start)
    section = text[start:end]
    section = re.sub(r'- \*\*当前状态/证据级别\*\*：[^\n]*', f'- **当前状态/证据级别**：{status}。', section)
    section = section.split('\n- **修复记录（2026-11-27）**')[0].rstrip()
    section += '\n- **修复记录（2026-11-27）**：' + details + '\n'
    PATH.write_text(text[:start] + section + '\n' + text[end:], encoding='utf-8')

if __name__ == '__main__':
    import sys
    update(int(sys.argv[1]), sys.argv[2], sys.argv[3])
