"""Render the Adamas sharing card and icon from the existing outlined wordmark.

Requires fonttools and the rsvg-convert command only when regenerating assets.
"""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'docs/assets/adamas'
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def text_paths(parent, text, x, y, size, color, font):
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / font['head'].unitsPerEm
    group = ET.SubElement(parent, f'{{{NS}}}g', {
        'transform': f'translate({x} {y}) scale({scale} {-scale})', 'fill': color})
    cursor = 0
    for char in text:
        name = cmap[ord(char)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(pen)
        if pen.getCommands():
            ET.SubElement(group, f'{{{NS}}}path', {
                'd': pen.getCommands(), 'transform': f'translate({cursor} 0)'})
        cursor += glyphs[name].width


def build():
    svg = ET.Element(f'{{{NS}}}svg', {'width': '1200', 'height': '630',
        'viewBox': '0 0 1200 630', 'role': 'img', 'aria-label': 'SaMuGeD Earworms. Listen, loop and explore musical phrases.'})
    ET.SubElement(svg, f'{{{NS}}}rect', {'width': '1200', 'height': '630', 'fill': '#101012'})
    ET.SubElement(svg, f'{{{NS}}}path', {'d': 'M60 70H1140M60 555H1140', 'stroke': '#303036'})
    font = TTFont(ROOT / 'docs/assets/inter/Inter.ttf')
    text_paths(svg, 'SaMuGeD Earworms', 60, 120, 21, '#b9acf3', font)
    logo = ET.parse(ASSETS / 'samuged-earworms.svg').getroot()
    logo.attrib.update({'x': '60', 'y': '175', 'width': '1080', 'height': '100'})
    svg.append(logo)
    text_paths(svg, 'Ostinato / Catchy musical hooks', 60, 340, 31, '#f0f0f2', font)
    text_paths(svg, 'Listen. Loop. Explore.', 60, 410, 26, '#9999a3', font)
    text_paths(svg, 'Melody + drums     /     MIDI + lossless audio', 60, 510, 21, '#b9acf3', font)
    target = ASSETS / 'social-preview-adamas-v1.svg'
    ET.ElementTree(svg).write(target, encoding='utf-8', xml_declaration=True)
    subprocess.run(['rsvg-convert', str(target), '-o', str(target.with_suffix('.png'))], check=True)
    icon = ET.Element(f'{{{NS}}}svg', {'viewBox': '-100 -1113 1100 1250', 'role': 'img', 'aria-label': 'SaMuGeD'})
    ET.SubElement(icon, f'{{{NS}}}rect', {'x': '-100', 'y': '-1113', 'width': '1100', 'height': '1250', 'fill': '#101012'})
    group = ET.SubElement(icon, f'{{{NS}}}g', {'transform': 'scale(1 -1)', 'fill': '#b9acf3'})
    path = ET.fromstring(ET.tostring(logo.find(f'{{{NS}}}g/{{{NS}}}path')))
    path.set('stroke', '#b9acf3')
    group.append(path)
    ET.ElementTree(icon).write(ASSETS / 'favicon-adamas.svg', encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    build()
