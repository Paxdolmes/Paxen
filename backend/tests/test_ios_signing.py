"""The CI signing patch must touch only the app target's Release configuration (.github/scripts/ios_signing.py)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".github/scripts"))
import ios_signing  # noqa: E402

BLOCK = """\t\t{id} /* {name} */ = {{
\t\t\tisa = XCBuildConfiguration;
{base}\t\t\tbuildSettings = {{
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
    # after `pod install`, the app's configurations reference the Pods xcconfig before their buildSettings
    pods = "\t\t\tbaseConfigurationReference = 1A2B /* Pods-Paxen.release.xcconfig */;\n"
    text = "".join([BLOCK.format(id="A1", name="Debug", bundle=app, base=pods), BLOCK.format(id="A2", name="Release", bundle=app, base=pods),
                    BLOCK.format(id="P1", name="Debug", bundle="", base=""), BLOCK.format(id="P2", name="Release", bundle="", base="")])
    out = ios_signing.patch_project(text, "TEAM123", "Paxen App Store CI", "com.paxdolmes.paxen")
    assert configs(out) == {("Debug", True): False, ("Release", True): True, ("Debug", False): False,
                            ("Release", False): False}
    assert out.count('PROVISIONING_PROFILE_SPECIFIER = "Paxen App Store CI";') == 1


def test_the_widget_target_gets_its_own_profile_in_a_real_project():
    """Against the project `expo prebuild` generates with the widget extension (quoted values, name before isa)."""
    widget = """\t\t93FD /* Release */ = {
\t\t\tname = Release;
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "com.paxdolmes.paxen.widgets";
\t\t\t\tCODE_SIGN_ENTITLEMENTS = "ExpoWidgetsTarget/ExpoWidgetsTarget.entitlements";
\t\t\t};
\t\t};
"""
    app = '\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "com.paxdolmes.paxen";\n'
    text = BLOCK.format(id="A2", name="Release", bundle=app, base="") + widget
    out = ios_signing.patch_project(text, "TEAM123", "Paxen App Store CI", "com.paxdolmes.paxen")
    out = ios_signing.patch_project(out, "TEAM123", "Paxen Widgets App Store CI", "com.paxdolmes.paxen.widgets")
    assert out.count('PROVISIONING_PROFILE_SPECIFIER = "Paxen App Store CI";') == 1
    assert out.count('PROVISIONING_PROFILE_SPECIFIER = "Paxen Widgets App Store CI";') == 1
    w = out[out.index("93FD"):]
    assert 'PROVISIONING_PROFILE_SPECIFIER = "Paxen Widgets App Store CI";' in w and "CODE_SIGN_STYLE = Manual" in w


def test_a_profile_without_the_app_group_is_noticed():
    with_group = (b"junk<key>com.apple.security.application-groups</key>\n<array>\n"
                  b"<string>group.com.paxdolmes.paxen</string></array>junk")
    assert ios_signing.profile_has_group(with_group, "group.com.paxdolmes.paxen")
    assert not ios_signing.profile_has_group(with_group, "group.other")
    empty = b"<key>com.apple.security.application-groups</key><array/>"
    assert not ios_signing.profile_has_group(empty, "group.com.paxdolmes.paxen")
    assert not ios_signing.profile_has_group(b"<key>aps-environment</key>", "group.com.paxdolmes.paxen")
