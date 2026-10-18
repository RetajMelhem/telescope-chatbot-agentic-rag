"""Run the actual UI text renderer in Node; no browser/network or visual claim."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is needed for UI JavaScript checks")
HTML = Path(__file__).parents[2] / "src/telescope_rag/api/local_chat.html"

CASES = [
    ("اتصل على 06 552 3333 أو واتساب +962 7 7752 3333.", ["06 552 3333", "+962 7 7752 3333"]),
    ("من 09:00 إلى 24:00 يوم الجمعة.", ["09:00", "24:00"]),
    ("Hours: 09:00 – 24:00", ["09:00 – 24:00"]),
    ("الرقم +٩٦٢ ٧ ٧٧٥٢ ٣٣٣٣", ["+٩٦٢ ٧ ٧٧٥٢ ٣٣٣٣"]),
    ("القيمة - ١٢٫٥ والرقم + 962 7 7752 3333", ["- ١٢٫٥", "+ 962 7 7752 3333"]),
    ("السعر ١٢.٥ والنتيجة -1.25 بتاريخ 2026-10-18", ["١٢.٥", "-1.25", "2026-10-18"]),
    ("اتصل على +962\u00a07\u00a07752\u00a03333\nسطر آخر", ["+962\u00a07\u00a07752\u00a03333"]),
    ('<img src=x onerror="alert(1)"> نص غير موثوق', ["1"]),
    ("نص عربي بدون أرقام. Plain English.", []),
]


@pytest.mark.parametrize("text,numbers", CASES)
def test_original_text_and_numeric_order_are_preserved_in_isolated_safe_nodes(text, numbers):
    renderer = re.search(
        r"function renderMixedText\(.*?\n}", HTML.read_text(encoding="utf-8"), re.S
    )
    assert renderer is not None
    harness = r"""
const vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Node {
 constructor(tag){this.tag=tag;this.children=[];this.value='';}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 set textContent(value){this.children=[];this.value=value;}
 get textContent(){return this.value+this.children.map(c=>c.textContent).join('');}
}
const document={createElement:tag=>new Node(tag),createDocumentFragment:()=>new Node('fragment'),
 createTextNode:text=>{const n=new Node('text');n.textContent=text;return n;}};
const root=new Node('root');const context={document,root,text:input.text};
vm.runInNewContext(input.renderer+';renderMixedText(root,text);',context);
const flatten=n=>[n,...n.children.flatMap(flatten)];const nodes=flatten(root);
console.log(JSON.stringify({text:root.textContent,
 numbers:nodes.filter(n=>n.tag==='bdi').map(n=>({text:n.textContent,dir:n.dir})),
 tags:nodes.map(n=>n.tag)}));
"""
    result = subprocess.run(
        [NODE, "-e", harness],
        input=json.dumps({"renderer": renderer.group(), "text": text}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=10,
    )
    output = json.loads(result.stdout)
    assert output["text"] == text
    assert output["numbers"] == [{"text": value, "dir": "ltr"} for value in numbers]
    assert set(output["tags"]) <= {"root", "fragment", "bdi", "text"}
