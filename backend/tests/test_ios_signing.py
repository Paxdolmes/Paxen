"""The CI signing patch must touch only the app target's Release configuration (.github/scripts/ios_signing.py)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".github/scripts"))
import ios_signing  # noqa: E402

BLOCK = """\t\t{id} /* {name} */ = {{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {{
\t\t\t\tCODE_SIGN_ENTITLEMENTS = Paxen/Paxen.entitlements;
{bundle}\t\t\t}};
\t\t\tname = {name};
\t\t}};
"""


def configs(text: str) -> dict[tuple[str, bool], bool]:
    out = {}
    for m in re.finditer(r"/\* (\w+) \*/ = \{\s*isa = XCBuildConfiguration;(.*?)name = \w+;", text, re.S):
        out[(m.group(1), "com.paxdolmes.paxen" in m.group(2))] = "CODE_SIGN_STYLE = Manual" in m.group(2)
    return out


def test_only_the_app_release_configuration_is_signed():
    app = '\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "com.paxdolmes.paxen";\n'
    text = "".join([BLOCK.format(id="A1", name="Debug", bundle=app), BLOCK.format(id="A2", name="Release", bundle=app),
                    BLOCK.format(id="P1", name="Debug", bundle=""), BLOCK.format(id="P2", name="Release", bundle="")])
    out = ios_signing.patch_project(text, "TEAM123", "Paxen App Store CI", "com.paxdolmes.paxen")
    assert configs(out) == {("Debug", True): False, ("Release", True): True, ("Debug", False): False,
                            ("Release", False): False}
    assert out.count('PROVISIONING_PROFILE_SPECIFIER = "Paxen App Store CI";') == 1
