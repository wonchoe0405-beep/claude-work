# 카톡 등으로 보내 폰에서 바로 여는 한 파일 버전: 라이브러리를 안에 넣고, PDF는 브라우저 다운로드로 저장한다.
import re
t = open('lexicon.html', encoding='utf-8').read()
def rep(a, b):
    global t
    assert t.count(a) == 1, a
    t = t.replace(a, b)
lib = lambda p: '<script>' + open(p, encoding='utf-8').read() + '</script>'
rep('<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js"></script>', lib('pdflib/dist/pdf-lib.min.js'))
rep('<script src="https://cdn.jsdelivr.net/npm/@pdf-lib/fontkit@1.1.1/dist/fontkit.umd.min.js"></script>', lib('fk/dist/fontkit.umd.min.js'))
rep('''  try { downloads = window.claude && window.claude.use ? await window.claude.use("downloads") : null; } catch { downloads = null; }''',
'''  downloads = {
    async save({ filename, data }) {
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      return { status: "saved" };
    },
  };''')
rep('`${answers ? "정답지" : "시험지"} PDF를 저장했습니다.`', '`${answers ? "정답지" : "시험지"} PDF를 내려받았습니다. 휴대폰의 ‘다운로드’ 폴더(내 파일)에서 열 수 있습니다.`')
head = '''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style>
'''
title_end = t.index('</title>') + len('</title>')
style_end = t.index('</style>') + len('</style>')
t = head + t[:style_end] + '\n</head>\n<body>\n' + t[style_end:] + '\n</body>\n</html>\n'
open('어휘끝_문제지.html', 'w', encoding='utf-8').write(t)
print(len(t.encode()))
