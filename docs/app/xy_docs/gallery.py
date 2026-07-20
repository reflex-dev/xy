"""Visual chart-type gallery for the XY documentation landing pages."""

from __future__ import annotations

from dataclasses import dataclass

import reflex as rx
import reflex_components_internal as ui


@dataclass(frozen=True, slots=True)
class GalleryItem:
    """One chart preview within a documentation family."""

    title: str
    fragment: str | None = None
    route: str | None = None


@dataclass(frozen=True, slots=True)
class GalleryGroup:
    """A gallery family with its overview route and preview items."""

    title: str
    route: str | None
    items: tuple[GalleryItem, ...]


_GALLERY_LAYOUT_CSS = """
main:has(#xy-chart-gallery) > div:has(#toc-navigation) {
  display: none;
}
main:has(#xy-chart-gallery) > div:has(article #xy-chart-gallery) {
  max-width: 88rem;
}
#xy-chart-gallery {
  --gallery-preview-surface: #fff;
  --gallery-preview-fill: #efeaff;
  --gallery-preview-soft: #dccfff;
  --gallery-preview-bar: #dccfff;
  --gallery-preview-stroke: #a790f0;
  --gallery-preview-strong: #8067d7;
}
.dark #xy-chart-gallery {
  --gallery-preview-surface: var(--secondary-2);
  --gallery-preview-fill: var(--primary-3);
  --gallery-preview-soft: var(--primary-5);
  --gallery-preview-bar: var(--primary-5);
  --gallery-preview-stroke: var(--primary-8);
  --gallery-preview-strong: var(--primary-9);
}
#xy-chart-gallery .preview-fill { fill: var(--gallery-preview-fill); }
#xy-chart-gallery .preview-fill-soft { fill: var(--gallery-preview-soft); }
#xy-chart-gallery .preview-bar { fill: var(--gallery-preview-bar); }
#xy-chart-gallery .preview-fill-strong { fill: var(--gallery-preview-stroke); }
#xy-chart-gallery .preview-line {
  fill: none;
  stroke: var(--gallery-preview-stroke);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
#xy-chart-gallery .preview-line-soft { stroke: var(--gallery-preview-soft); }
#xy-chart-gallery .preview-stroke {
  stroke: var(--gallery-preview-stroke);
  stroke-width: 2;
}
#xy-chart-gallery .preview-dashed { stroke-dasharray: 5 5; }
#xy-chart-gallery .preview-dot { fill: var(--gallery-preview-strong); }
#xy-chart-gallery .preview-dot-soft { fill: var(--gallery-preview-stroke); }
#xy-chart-gallery .preview-scatter-low {
  fill: var(--gallery-preview-soft);
  opacity: .68;
}
#xy-chart-gallery .preview-scatter-mid {
  fill: var(--gallery-preview-stroke);
  opacity: .8;
}
#xy-chart-gallery .preview-scatter-high {
  fill: var(--gallery-preview-strong);
  opacity: .92;
}
#xy-chart-gallery .preview-label-line {
  fill: none;
  stroke: var(--gallery-preview-strong);
  stroke-width: 2;
  stroke-linecap: round;
  opacity: .55;
}
#xy-chart-gallery .preview-text-line {
  fill: none;
  stroke: var(--gallery-preview-soft);
  stroke-width: 7;
  stroke-linecap: round;
}
#xy-chart-gallery .preview-panel {
  fill: var(--gallery-preview-fill);
  stroke: var(--gallery-preview-soft);
}
#xy-chart-gallery .preview-mini-line {
  fill: none;
  stroke: var(--gallery-preview-stroke);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
#xy-chart-gallery .preview-heatmap rect { fill: var(--gallery-preview-soft); }
#xy-chart-gallery .preview-heatmap rect:nth-child(3n + 1) {
  fill: var(--gallery-preview-fill);
}
#xy-chart-gallery .preview-heatmap rect:nth-child(4n) {
  fill: var(--gallery-preview-stroke);
}
"""


_GALLERY_GROUPS: tuple[GalleryGroup, ...] = (
    GalleryGroup(
        "Line and Area",
        "/charts/line-and-area/",
        (
            GalleryItem("Line"),
            GalleryItem("Area"),
            GalleryItem("Step + Stairs", "step-and-stairs"),
        ),
    ),
    GalleryGroup(
        "Distributions",
        "/charts/distributions/",
        (
            GalleryItem("Histogram"),
            GalleryItem("ECDF", "ecdf"),
            GalleryItem("Box", "box"),
            GalleryItem("Violin", "violin"),
        ),
    ),
    GalleryGroup(
        "Bar, Column, and Scatter",
        None,
        (
            GalleryItem("Bar + Column", route="/charts/bar-and-column/"),
            GalleryItem("Scatter", route="/charts/scatter/"),
        ),
    ),
    GalleryGroup(
        "Density and Grids",
        "/charts/density-and-grids/",
        (
            GalleryItem("Hexbin", "hexbin"),
            GalleryItem("Heatmap"),
            GalleryItem("Contour", "contour"),
        ),
    ),
    GalleryGroup(
        "Uncertainty",
        "/charts/uncertainty/",
        (
            GalleryItem("Error Band"),
            GalleryItem("Error Bar"),
        ),
    ),
    GalleryGroup(
        "Specialized",
        "/charts/specialized/",
        (
            GalleryItem("Stem"),
            GalleryItem("Segments", "segments"),
            GalleryItem("Triangle Mesh", "triangle-mesh"),
        ),
    ),
    GalleryGroup(
        "Annotations",
        "/components/annotations/",
        (
            GalleryItem("Threshold", "threshold"),
            GalleryItem("Horizontal Line", "horizontal-line"),
            GalleryItem("Vertical Line"),
            GalleryItem("Bands", "bands"),
            GalleryItem("Callout"),
            GalleryItem("Arrow", "arrow"),
            GalleryItem("Label", "label"),
            GalleryItem("Text", "text"),
            GalleryItem("Threshold Zone"),
        ),
    ),
    GalleryGroup(
        "Facets and Layers",
        "/charts/facets-and-layers/",
        (
            GalleryItem("Facet Chart", "facet-chart"),
            GalleryItem("Layered Marks"),
        ),
    ),
)
_GALLERY_PREVIEW_ART = {
    "Line": """
<path d="M43 151.5L96.5 116L161 132L277.5 111.5" class="preview-line preview-line-soft"/>
<path d="M43.5 129.5L109 141.5L144.5 79.5L207.5 153L272 97.5" class="preview-line"/>
<circle cx="109" cy="141" r="3" class="preview-dot"/><circle cx="145" cy="80" r="3" class="preview-dot"/><circle cx="208" cy="152" r="3" class="preview-dot"/><circle cx="160" cy="132" r="3" class="preview-dot-soft"/><circle cx="96" cy="116" r="3" class="preview-dot-soft"/>
""",
    "Area": """
<path d="M109 142.5C81.5 142.5 67.5 83 42 83V172H284.5V100H276C235.5 100 236.5 134 210 134C183.5 134 179.5 103 160 103C140.5 103 136.5 142.5 109 142.5Z" class="preview-fill"/>
<path d="M42 83C67.5 83 81.5 142.5 109 142.5C136.5 142.5 140.5 103 160 103C179.5 103 183.5 134 210 134C236.5 134 235.5 100 276 100" class="preview-line"/>
""",
    "Step + Stairs": """
<path d="M42 145H78V120H116V135H154V92H194V112H232V78H278" class="preview-line"/>
<path d="M42 156H92V142H132V150H174V120H214V132H252V104H278" class="preview-line preview-line-soft"/>
""",
    "Scatter": """
<circle cx="86" cy="145" r="2.5" class="preview-scatter-low"/><circle cx="101" cy="132" r="4" class="preview-scatter-mid"/><circle cx="113" cy="141" r="3" class="preview-scatter-high"/><circle cx="119" cy="113" r="4.5" class="preview-scatter-low"/><circle cx="134" cy="125" r="3.5" class="preview-scatter-mid"/><circle cx="146" cy="106" r="5" class="preview-scatter-high"/><circle cx="158" cy="117" r="2.5" class="preview-scatter-low"/><circle cx="171" cy="95" r="4" class="preview-scatter-mid"/><circle cx="184" cy="105" r="4.5" class="preview-scatter-low"/><circle cx="194" cy="84" r="3.5" class="preview-scatter-high"/><circle cx="207" cy="98" r="3" class="preview-scatter-mid"/><circle cx="219" cy="77" r="4.5" class="preview-scatter-low"/><circle cx="232" cy="88" r="3.5" class="preview-scatter-high"/><circle cx="242" cy="70" r="2.5" class="preview-scatter-mid"/>
""",
    "Bar + Column": """
<rect x="60" y="126" width="18" height="36" rx="4" class="preview-bar"/><rect x="86" y="88" width="18" height="74" rx="4" class="preview-bar"/><rect x="112" y="104" width="18" height="58" rx="4" class="preview-bar"/><rect x="138" y="76" width="18" height="86" rx="4" class="preview-bar"/><rect x="164" y="128" width="18" height="34" rx="4" class="preview-bar"/><rect x="190" y="92" width="18" height="70" rx="4" class="preview-bar"/><rect x="216" y="113" width="18" height="49" rx="4" class="preview-bar"/><rect x="242" y="130" width="18" height="32" rx="4" class="preview-bar"/>
""",
    "Histogram": """
<rect x="68" y="137" width="24" height="23" rx="3" class="preview-fill-soft"/><rect x="94" y="115" width="24" height="45" rx="3" class="preview-fill-strong"/><rect x="120" y="88" width="24" height="72" rx="3" class="preview-fill-soft"/><rect x="146" y="74" width="24" height="86" rx="3" class="preview-fill-strong"/><rect x="172" y="98" width="24" height="62" rx="3" class="preview-fill-soft"/><rect x="198" y="120" width="24" height="40" rx="3" class="preview-fill-strong"/><rect x="224" y="142" width="24" height="18" rx="3" class="preview-fill-soft"/>
""",
    "ECDF": """
<path d="M58 150H88V137H112V122H137V108H165V92H194V79H224V68H260" class="preview-line"/>
<circle cx="112" cy="122" r="3" class="preview-dot"/><circle cx="165" cy="92" r="3" class="preview-dot"/><circle cx="224" cy="68" r="3" class="preview-dot"/>
""",
    "Box": """
<path d="M66 116H105M215 116H254M66 105V127M254 105V127" class="preview-line preview-line-soft"/><rect x="105" y="92" width="110" height="48" rx="7" class="preview-fill preview-stroke"/><path d="M160 92V140" class="preview-line"/><circle cx="272" cy="116" r="4" class="preview-dot"/>
""",
    "Violin": """
<path d="M160 69C149 78 145 91 129 104C116 115 118 126 136 137C149 145 154 153 160 163C166 153 171 145 184 137C202 126 204 115 191 104C175 91 171 78 160 69Z" class="preview-fill-soft preview-stroke"/><path d="M160 80V152M147 116H173" class="preview-line"/>
""",
    "Hexbin": """
<path d="M107 86l13-7 13 7v14l-13 7-13-7zM137 104l13-7 13 7v14l-13 7-13-7zM167 86l13-7 13 7v14l-13 7-13-7zM197 104l13-7 13 7v14l-13 7-13-7zM107 122l13-7 13 7v14l-13 7-13-7zM167 122l13-7 13 7v14l-13 7-13-7zM137 140l13-7 13 7v14l-13 7-13-7z" class="preview-fill-soft"/><path d="M137 104l13-7 13 7v14l-13 7-13-7zM167 122l13-7 13 7v14l-13 7-13-7z" class="preview-fill-strong"/>
""",
    "Heatmap": """
<g class="preview-heatmap"><rect x="101" y="75" width="28" height="24"/><rect x="133" y="75" width="28" height="24"/><rect x="165" y="75" width="28" height="24"/><rect x="197" y="75" width="28" height="24"/><rect x="101" y="103" width="28" height="24"/><rect x="133" y="103" width="28" height="24"/><rect x="165" y="103" width="28" height="24"/><rect x="197" y="103" width="28" height="24"/><rect x="101" y="131" width="28" height="24"/><rect x="133" y="131" width="28" height="24"/><rect x="165" y="131" width="28" height="24"/><rect x="197" y="131" width="28" height="24"/></g>
""",
    "Contour": """
<path d="M76 123C92 83 128 72 160 84C190 57 247 78 247 116C247 151 202 160 166 143C130 169 88 155 76 123Z" class="preview-line preview-line-soft"/><path d="M105 122C113 95 139 90 162 99C184 80 218 94 219 117C219 140 190 147 166 134C142 151 113 143 105 122Z" class="preview-line"/><path d="M137 119C142 106 157 105 168 111C180 102 194 109 194 120C194 132 180 136 168 129C156 137 142 132 137 119Z" class="preview-fill-soft"/>
""",
    "Error Band": """
<path d="M44 132C75 110 92 117 121 91C150 66 177 98 204 85C232 72 252 80 278 67V108C250 119 231 109 207 122C178 137 151 105 123 130C93 157 71 143 44 157Z" class="preview-fill"/><path d="M44 145C75 124 93 130 122 108C151 84 178 118 206 103C232 90 253 99 278 86" class="preview-line"/>
""",
    "Error Bar": """
<path d="M105 117V139M101 117H109M101 139H109M97 129H115M97 125V133M115 125V133M158 90V108M154 90H162M154 108H162M142 98H176M142 94V102M176 94V102M216 126V148M212 126H220M212 148H220M206 134H230M206 130V138M230 130V138" class="preview-line preview-line-soft"/><circle cx="105" cy="129" r="4" class="preview-dot"/><circle cx="158" cy="98" r="4" class="preview-dot"/><circle cx="216" cy="134" r="4" class="preview-dot"/>
""",
    "Stem": """
<path d="M70 155H250M92 155V121M126 155V92M160 155V110M194 155V75M228 155V129" class="preview-line preview-line-soft"/><circle cx="92" cy="121" r="5" class="preview-dot"/><circle cx="126" cy="92" r="5" class="preview-dot"/><circle cx="160" cy="110" r="5" class="preview-dot"/><circle cx="194" cy="75" r="5" class="preview-dot"/><circle cx="228" cy="129" r="5" class="preview-dot"/>
""",
    "Segments": """
<path d="M72 139L108 110M115 145L149 89M156 128L199 105M204 137L249 79" class="preview-line"/><circle cx="72" cy="139" r="3.5" class="preview-dot-soft"/><circle cx="108" cy="110" r="3.5" class="preview-dot"/><circle cx="115" cy="145" r="3.5" class="preview-dot-soft"/><circle cx="149" cy="89" r="3.5" class="preview-dot"/><circle cx="156" cy="128" r="3.5" class="preview-dot-soft"/><circle cx="199" cy="105" r="3.5" class="preview-dot"/><circle cx="204" cy="137" r="3.5" class="preview-dot-soft"/><circle cx="249" cy="79" r="3.5" class="preview-dot"/>
""",
    "Triangle Mesh": """
<path d="M72 147L105 87L143 139L175 73L214 121L249 82L262 151H72Z" class="preview-fill"/><path d="M72 147L105 87L143 139L175 73L214 121L249 82L262 151M72 147L143 139L214 121L262 151M105 87L175 73L249 82M105 87L143 139L175 73L214 121L249 82" class="preview-line preview-line-soft"/>
""",
    "Threshold": """
<path d="M54 112H266" class="preview-line preview-dashed"/><path d="M64 143L104 128L144 136L184 96L224 102L260 79" class="preview-line"/><rect x="199" y="72" width="49" height="18" rx="5" class="preview-fill-soft"/><path d="M208 81H239" class="preview-label-line"/>
""",
    "Horizontal Line": """
<path d="M54 116H266" class="preview-line"/><path d="M74 147C107 133 132 140 158 105C181 75 211 96 250 77" class="preview-line preview-line-soft"/>
""",
    "Vertical Line": """
<path d="M160 70V162" class="preview-line"/><path d="M66 145C101 126 122 137 151 105C180 73 209 104 254 80" class="preview-line preview-line-soft"/>
""",
    "Bands": """
<rect x="93" y="62" width="44" height="108" class="preview-fill"/><rect x="185" y="62" width="50" height="108" class="preview-fill"/><path d="M52 143C90 120 119 138 153 100C185 65 215 102 268 79" class="preview-line"/>
""",
    "Callout": """
<circle cx="126" cy="136" r="6" class="preview-dot"/><path d="M131 131L167 94" class="preview-line"/><rect x="160" y="75" width="86" height="28" rx="8" class="preview-fill-soft"/><path d="M172 86H233M172 93H213" class="preview-label-line"/>
""",
    "Arrow": """
<path d="M88 143L216 88M203 81L216 88L210 102" class="preview-line"/><circle cx="88" cy="143" r="5" class="preview-dot-soft"/>
""",
    "Label": """
<path d="M70 145C106 126 133 139 160 103C185 70 216 101 251 81" class="preview-line preview-line-soft"/><circle cx="160" cy="103" r="5" class="preview-dot"/><path d="M164 99L181 87" class="preview-line"/><rect x="176" y="70" width="65" height="26" rx="7" class="preview-fill-soft"/><path d="M188 83H229" class="preview-label-line"/>
""",
    "Text": """
<path d="M80 97H207M80 116H239M80 135H183" class="preview-text-line"/><rect x="80" y="76" width="72" height="8" rx="4" class="preview-fill-strong"/>
""",
    "Threshold Zone": """
<rect x="52" y="112" width="216" height="58" class="preview-fill"/><path d="M52 112H268" class="preview-line preview-dashed"/><path d="M64 144L103 130L142 138L181 98L220 118L257 87" class="preview-line"/>
""",
    "Facet Chart": """
<rect x="70" y="75" width="82" height="36" rx="6" class="preview-panel"/><rect x="168" y="75" width="82" height="36" rx="6" class="preview-panel"/><rect x="70" y="121" width="82" height="36" rx="6" class="preview-panel"/><rect x="168" y="121" width="82" height="36" rx="6" class="preview-panel"/><path d="M78 103L96 91L113 98L127 83L144 92M176 102L194 86L211 94L226 81L242 88M78 147L96 137L113 142L128 128L144 135M176 149L194 133L211 140L226 126L242 131" class="preview-mini-line"/>
""",
    "Layered Marks": """
<path d="M110.5 128C82.9 128 73.6 153.5 48 153.5V172.5H291L293 151H284.5C243.9 151 241.6 120 215 120C188.4 120 179.8 151 163 151C146.2 151 138.1 128 110.5 128Z" class="preview-fill"/><rect x="82" y="126" width="18" height="36" rx="4" class="preview-fill-soft"/><rect x="128" y="120" width="18" height="42" rx="4" class="preview-fill-soft"/><rect x="174" y="138" width="18" height="24" rx="4" class="preview-fill-soft"/><rect x="220" y="106" width="18" height="56" rx="4" class="preview-fill-soft"/><path d="M276 90C250.5 90 236.5 149.5 209 149.5C181.5 149.5 177.5 110 158 110C138.5 110 134.5 141 108 141C81.5 141 82.5 107 42 107" class="preview-line"/>
""",
}


def _gallery_preview_svg(title: str) -> str:
    """Return a code-native preview SVG styled like the Reflex component tiles."""
    preview_id = "gallery-" + "".join(
        character.lower() for character in title if character.isalnum()
    )
    art = _GALLERY_PREVIEW_ART[title]
    return f"""
<svg viewBox="0 0 320 232" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
  <g filter="url(#{preview_id}-shadow)">
    <g clip-path="url(#{preview_id}-clip)">
      <rect x="52" y="62" width="216" height="108" rx="12" fill="var(--gallery-preview-surface)"/>
      {art}
    </g>
  </g>
  <defs>
    <filter id="{preview_id}-shadow" x="32" y="54" width="256" height="148" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
      <feFlood flood-opacity="0" result="BackgroundImageFix"/>
      <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
      <feOffset dy="12"/>
      <feGaussianBlur stdDeviation="10"/>
      <feComposite in2="hardAlpha" operator="out"/>
      <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.03 0"/>
      <feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow"/>
      <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
      <feOffset dy="2"/>
      <feGaussianBlur stdDeviation="3"/>
      <feComposite in2="hardAlpha" operator="out"/>
      <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.05 0"/>
      <feBlend mode="normal" in2="effect1_dropShadow" result="effect2_dropShadow"/>
      <feBlend mode="normal" in="SourceGraphic" in2="effect2_dropShadow" result="shape"/>
    </filter>
    <clipPath id="{preview_id}-clip"><rect x="52" y="62" width="216" height="108" rx="12"/></clipPath>
  </defs>
</svg>
"""


def _gallery_preview(title: str) -> rx.Component:
    """Render an editable inline SVG without creating a WebGL context."""
    return rx.html(
        _gallery_preview_svg(title),
        class_name="h-full w-full [&>svg]:h-full [&>svg]:w-full",
    )


def _gallery_card(item: GalleryItem, group_route: str | None) -> rx.Component:
    """Render one linked chart-type preview card."""
    route = item.route or group_route
    if route is None:
        msg = f"Gallery item {item.title!r} needs an item or group route"
        raise ValueError(msg)
    destination = f"{route}#{item.fragment}" if item.fragment else route
    return rx.link(
        rx.box(
            _gallery_preview(item.title),
            rx.box(
                rx.text(
                    item.title,
                    class_name="truncate font-base text-secondary-12",
                ),
                ui.icon(
                    "ArrowRight01Icon",
                    size=14,
                    class_name="text-secondary-9",
                ),
                class_name=(
                    "absolute bottom-0 flex w-full flex-row items-center justify-between px-4 py-2"
                ),
            ),
            class_name=(
                "relative aspect-[320/232] overflow-hidden rounded-xl border "
                "box-border border-secondary-5 bg-secondary-2 shadow-large "
                "transition-bg hover:bg-secondary-3"
            ),
        ),
        href=destination,
        underline="none",
        class_name="block !text-inherit",
        aria_label=f"Open the {item.title} guide",
    )


def _gallery_group_heading(group: GalleryGroup) -> rx.Component:
    """Render a linked family heading or a plain mixed-family heading."""
    heading = rx.el.h2(
        group.title,
        class_name="font-large text-secondary-12",
    )
    if group.route is None:
        return heading
    return rx.link(
        heading,
        href=group.route,
        underline="none",
        class_name="!text-inherit hover:!text-primary-10",
        aria_label=f"Open the {group.title} chart family guide",
    )


def chart_gallery_grid() -> rx.Component:
    """Render every public chart type, grouped like the Chart Gallery."""
    return rx.fragment(
        rx.el.style(_GALLERY_LAYOUT_CSS),
        rx.el.div(
            *(
                rx.el.section(
                    _gallery_group_heading(group),
                    rx.el.div(
                        *(_gallery_card(item, group.route) for item in group.items),
                        class_name=("grid w-full grid-cols-1 gap-8 md:grid-cols-2 2xl:grid-cols-3"),
                    ),
                    class_name="flex w-full flex-col gap-4",
                )
                for group in _GALLERY_GROUPS
            ),
            id="xy-chart-gallery",
            class_name="my-8 flex w-full flex-col gap-14",
        ),
    )


__all__ = ["chart_gallery_grid"]
