"""Execute the actual social-link DOM renderer; no external navigation or browser."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node needed for UI checks")
HTML = Path(__file__).parents[2] / "src/telescope_rag/api/local_chat.html"


@pytest.mark.parametrize(
    "invalid",
    [
        "javascript:alert(1)",
        "https://www.facebook.com.evil.test/fake",
        "http://www.facebook.com/fake",
        "https://user@www.facebook.com/fake",
        "https://www.facebook.com:8000/fake",
        "https://www.facebook.com/fake?next=evil",
    ],
)
def test_only_reviewed_target_hosts_are_linked_and_occurrences_keep_source_proof(invalid):
    renderer = re.search(
        r"function renderWebsiteLinks\(.*?\n}", HTML.read_text(encoding="utf-8"), re.S
    ).group()
    base = {
        "platform": "Facebook",
        "target_url": "https://www.facebook.com/synthetic-only",
        "source_url": "https://telescopecenter.com/",
        "fetched_at": "synthetic timestamp",
        "literal_label": '<img onerror="evil">',
    }
    links = [
        base,
        {**base, "source_url": "https://telescopecenter.com/ar/"},
        {**base, "target_url": invalid},
    ]
    harness = r"""
const vm=require('node:vm'),input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Node{
 constructor(tag){this.tag=tag;this.children=[];this.value='';}
 append(...n){this.children.push(...n);}replaceChildren(...n){this.children=n;}
 set textContent(v){this.value=v;this.children=[];}
 get textContent(){return this.value+this.children.map(n=>n.textContent).join('');}
}
const document={createElement:t=>new Node(t),createDocumentFragment:()=>new Node('fragment'),
createTextNode:t=>{const n=new Node('text');n.textContent=t;return n;}};
const root=new Node('root');
vm.runInNewContext(input.renderer+';renderWebsiteLinks(root,links)',{document,root,links:input.links,URL});
const flat=n=>[n,...n.children.flatMap(flat)];const all=flat(root);
console.log(JSON.stringify({anchors:all.filter(n=>n.tag==='a').map(n=>({href:n.href,rel:n.rel,text:n.textContent})),
 text:root.textContent,tags:all.map(n=>n.tag)}));
"""
    result = subprocess.run(
        [NODE, "-e", harness],
        input=json.dumps({"renderer": renderer, "links": links}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=10,
    )
    output = json.loads(result.stdout)
    assert [a["href"] for a in output["anchors"]] == [
        base["target_url"],
        "https://telescopecenter.com/",
        "https://telescopecenter.com/ar/",
    ]
    assert all(a["rel"] == "noopener noreferrer" for a in output["anchors"])
    assert output["text"].count(base["literal_label"]) == 2
    assert set(output["tags"]) <= {"root", "fragment", "p", "a", "details", "summary", "br", "text"}
