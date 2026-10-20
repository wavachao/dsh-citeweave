# Answer quality review

This review covers the 12 answers in [results/2026-10-21](results/2026-10-21): three questions, plugin enabled or disabled, and two repetitions. The answering model was DeepSeek Flash with thinking disabled. Harness was `0.2.1-rc.2`; the evaluated plugin was `0.4.0` at commit `b57e48958d390e7d4c9acb5c07f8a7b43f392346`. These results do not evaluate subsequent releases.

All six enabled answers embedded images, with ten image placements in total. All six disabled answers explicitly reported that they could not obtain images. Inspection of the stored image bytes confirmed their relevance to the questions, with differences in explanatory detail noted below. Images did not eliminate factual errors or citation problems.

## Method and limits

The review checks three separate properties:

- **Fact coverage:** whether the answer explains the specific concepts requested. The checklists below cover core concepts, not every sentence or numerical claim.
- **Source traceability:** whether readers can follow a source link and identify which claim or image it accompanies. A bibliography or link count alone does not establish that the source supports every claim.
- **Image usefulness:** whether an actual returned image appears within the explanation and depicts the relevant concept. Image bytes were inspected before publication; the public transcripts link to their recorded original image URLs. Remote availability may change.

This is a manual, unblinded review of a small illustrative sample. It assigns no aggregate score, quality percentage, or statistical significance. Timing is reported separately from answer quality.

The Windows environment resolved several public domains to non-public addresses. Native Harness `web_fetch` rejected those addresses; native search still returned text summaries and links. The plugin backend retrieved pages through a different network path. Both conditions retained the same native tool configuration, but the retrieval paths were therefore not equivalent. The observed image difference cannot establish a general limitation of Harness or an advantage under normally functioning native fetch. No clean network control is included in this dataset.

## Eratosthenes and Earth's circumference

Core checklist:

- **E1:** solstice-noon shadow contrast between Syene and Alexandria.
- **E2:** parallel sunlight and local verticals explain why the measured angle equals the central angle.
- **E3:** `7.2 / 360 = 1 / 50`, hence circumference equals 50 times the intercity distance.
- **E4:** the conventional approximately 5,000-stadia distance and approximately 250,000-stadia circumference, with historical unit uncertainty allowed.

`Yes` means the concept is present; `Mixed` means the explanation contains conflicting or incorrect wording. It does not certify the entire answer.

| Answer | E1 | E2 | E3 | E4 | Images and traceability |
| --- | --- | --- | --- | --- | --- |
| [Disabled, repetition 1](results/2026-10-21/earth-off-r1.answer.md) | Yes | Mixed | Yes | Incorrect | No image; fetch failure disclosed. Clickable prose citations and bibliography. |
| [Enabled, repetition 1](results/2026-10-21/earth-on-r1.answer.md) | Yes | Yes | Yes | Yes | One relevant geometry diagram with an adjacent image-source link; text references collected at the end. |
| [Disabled, repetition 2](results/2026-10-21/earth-off-r2.answer.md) | Yes | Mixed | Yes | Yes | No image; unavailable image-page links clearly identified as unfetched. Text sources listed at the end. |
| [Enabled, repetition 2](results/2026-10-21/earth-on-r2.answer.md) | Yes | Mixed | Yes | Yes | One relevant geometry diagram, the same diagram as enabled repetition 1, with an image-source link. Text references listed at the end. |

Specific factual observations:

- **Disabled repetition 1** uses 2,400 stadia and 120,000 stadia, and calls 42,000 km the modern circumference. Those figures do not match the conventional account or the approximately 40,000 km modern value. Its claim that the vertical rod and the corresponding Earth radius form a triangle is also incorrect: those directions are collinear in the model. [NASA's account](https://imagine.gsfc.nasa.gov/features/cosmic/earth_info.html) gives the 5,000-stadia distance and 250,000-stadia calculation; [Bucknell's geometry explanation](https://www.eg.bucknell.edu/physics/astronomy/astr101/specials/eratosthenes.html) identifies the angle between sunlight and the vertical.
- **Enabled repetition 2** calls 7.2° the solar altitude angle. In this construction it is the displacement from the zenith; the corresponding altitude is 82.8°. Its parallel-ray reasoning and multiplication by 50 otherwise express the intended relationship. The additional 224,100-stadia / 40,338-km reconstruction is not counted as an invented number: it is discussed in [C. A. Matthew's historical analysis](https://researchers-admin.westernsydney.edu.au/ws/portalfiles/portal/94906355/uws_71622.pdf).
- **Disabled repetition 2** initially describes an angle between the rod and its shadow, then correctly specifies sunlight versus the rod. The later explanation repairs the intended geometry, but the earlier wording remains ambiguous.

The enabled diagram shows the parallel rays, the two local verticals, and the 1/50 fraction. It directly supports the requested geometric explanation. In enabled repetition 2, the final illustrated answer followed a plugin call that failed with 503, another that returned no images, and a later successful call. The final image therefore does not imply first-call success.

## Butterfly metamorphosis

All four answers cover the ordered **egg → larva → pupa → adult** sequence and explain the core roles: embryo protection, larval feeding and growth, pupal transformation, and adult reproduction. This coverage matches the [Florida Museum's life-cycle description](https://www.floridamuseum.ufl.edu/educators/resource/butterfly-life-cycle/).

| Answer | Images | Source traceability | Specific observation |
| --- | --- | --- | --- |
| [Disabled, repetition 1](results/2026-10-21/butterfly-off-r1.answer.md) | None; fetch failure disclosed | Clickable bibliography | Says the pupa cannot move; this is too absolute. |
| [Enabled, repetition 1](results/2026-10-21/butterfly-on-r1.answer.md) | Two relevant four-stage diagrams | Adjacent image-source links and bibliography; raw `[s0]`–`[s3]` text markers are not clickable or explicitly mapped | Also describes the pupa as not moving. The two diagrams largely repeat the same cycle. |
| [Disabled, repetition 2](results/2026-10-21/butterfly-off-r2.answer.md) | None; fetch failure disclosed | Clickable source list, with access limitation explained | Describes the larva as the only continuously feeding stage, while later describing adult nectar feeding. This wording overstates the contrast. |
| [Enabled, repetition 2](results/2026-10-21/butterfly-on-r2.answer.md) | Two relevant diagrams: a cycle and a hand-drawn cycle with stage functions | One prose link and a source list identifying the two figures | Core stage explanation is present. The egg-count and hatch-time figures are traceable to the linked Florida Museum page. |

Pupae can move their abdomen and move during emergence; “usually externally still” is more accurate than “cannot move.” The [Smithsonian's exhibit description](https://naturalhistory.si.edu/visit/accessibility/audio-and-visual-description/insect-zoo-audio-description-tour) describes a swallowtail pupa pulsing before emergence and contrasts larval and adult feeding. The visual material illustrates stage differences, but does not correct these overstatements in the accompanying text.

## HDD and SSD

All four answers cover the requested core contrasts: **magnetic platters and moving heads versus NAND and a controller; seek/rotational delay versus electronic access; mechanical vulnerability versus stronger shock resistance; and mechanical failure risks versus finite flash write endurance**. Coverage of those contrasts does not validate the additional implementation claims below.

| Answer | Images | Source traceability | Specific observation |
| --- | --- | --- | --- |
| [Disabled, repetition 1](results/2026-10-21/storage-off-r1.answer.md) | None; fetch failure disclosed | Clickable prose links | Presents DRAM as a necessary SSD component and describes HDD as a repairable category. |
| [Enabled, repetition 1](results/2026-10-21/storage-on-r1.answer.md) | Two useful annotated figures: HDD/SSD comparison and HDD components | Clickable paragraph citations, but no explicit figure-to-source labels; the nearest citation before the first image refers to a different source | Initially reverses seeking and rotational waiting, then describes the correct sequence later. |
| [Disabled, repetition 2](results/2026-10-21/storage-off-r2.answer.md) | None; fetch failure disclosed | Source list explicitly described as search summaries | Calls seeking rotation to a track; the head moves between tracks. Also implies every SSD write first erases a whole block. |
| [Enabled, repetition 2](results/2026-10-21/storage-on-r2.answer.md) | HDD platter/head photo and an SSD product photo with a “Controller NAND DRAM” title | Prose citations and a final list identifying the two image sources | Again reverses seeking and rotational waiting and treats DRAM as universal. The SSD image is relevant, but does not label individual chips as the caption suggests. |

The DRAM generalization is contradicted by products such as the [Samsung 980, explicitly documented as DRAM-less](https://news.samsung.com/us/980-nvme-ssd-combines-speed-and-affordability/?na=s). Block erase and page programming should distinguish writing an already erased page from reclaiming or updating previously programmed storage, as described in [Kingston's garbage-collection explanation](https://www.kingston.com/en/blog/servers-and-data-centers/garbage-collection). The HDD “repairable” classification also needs qualification: remapping sectors is not a general repair for an impending drive failure; [Seagate's SMART guidance](https://www.seagate.com/support/kb/my-system-reported-a-smart-error-on-the-drive-184619en/) explains when replacement is needed.

The strongest visual explanations in these storage samples are the annotated figures in enabled repetition 1. The enabled repetition 2 SSD cover image provides context but adds little component-level information. Both enabled answers still need factual editing.

## Interpretation

In this recorded environment, enabling CiteWeave produced relevant inline images for all three questions in both repetitions. The disabled answers disclosed missing images rather than fabricating image URLs. Both conditions contained factual errors or overstatements, and source-to-claim mapping varied between answers. These samples demonstrate an illustrated-answer workflow and its current citation limitations; they do not establish a general improvement in textual factual accuracy or a network-independent comparison of the two retrieval paths.
