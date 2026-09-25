import csv, json, base64
src='/home/user/claude-work/영영풀이 문제 생성기/개발/어휘끝_수능편_영영풀이.csv'
rows=list(csv.DictReader(open(src,encoding='utf-8-sig')))
data=[[int(r['day']),r['word'],r['definition'],r['korean']] for r in rows]
t=open('template.html',encoding='utf-8').read()
for n in ('r','b'): t=t.replace(f'__FONT_{n.upper()}__',base64.b64encode(open(f'f{n}.ttf','rb').read()).decode())
t=t.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/'))
open('lexicon.html','w',encoding='utf-8').write(t)
