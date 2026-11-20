# Splitting the organic layer's piece `main` into printable pieces

Started 20 Nov 2026, after revision 19, with the owner's go-ahead ("yes, you can start"). Nothing here is built. The sketch is `docs/plans/sketches/split_sketch.py`; it reads the saved field and changes nothing in `cad_b6/`.

## Why

`main` is one body, 515 x 408 x 381 mm (X -257..257, Y -23..385, Z -15..366). The printer's bed is 300 mm and the project's rule for a part is 290 (`frame_v0.MAX_PART`). The rear panel is already a piece of its own. Until `main` is split, the layer cannot be printed, and the skeleton parts that carry its pads (`rib_A`, `rib_B`, `neck`) cannot be called final.

## What earlier plans already say

- `cables-and-organic.md`: "The split into printable pieces of 290 mm or less, with joints, and the print orientation." And: "The front centre (brow, card bone, lip bone) spans 380 mm with no skeleton behind it. It passes the push test through the films, but it is the place to watch when the layer is split."
- `b6-frame-v0.md`: "ABS and PLA shrink differently, so the organic layer is fixed to the skeleton at a few points with slack, not along long seams." (The layer is PETG now; the point stands.)
- `rear-panel.md`: a piece fits the bed when, standing as built and turned about the vertical, its extents are at most 290 along both horizontal directions and along Z; for `main` the extents are reported and not failed. Two halves of a bar that end free in the middle "would need a screwed joint between them" (a 30 N push on a free end of a 131 mm bar of radius 6.5 is 18 MPa by hand).

## What `main` is made of (revision 19)

Sixteen bones: `lip` (X -190..190 at Y 64, Z 276), `card` (X -170..170 at Y -10, Z 196), `front_low` (X -160..160 at Y 22, Z 60, with the hood over the I/O module), the posts `front_R` (foot to the bone over the card and on to the lip's corner, 309 mm) and `front_L` (foot to the bone over the card, 193 mm), the rings `ring_R`, `ring_L` (222 mm squares round the side fans at X ±248), the side bones, the rear sweeps, the base rails (316 mm each, Y 40..356 at Z -4), and three ties of the left ring. Eight films hang between them. Twelve pads hold it, all on the flanks: two at each front foot, three at each rear (`base_mid`, `rear_foot`, `rear_post`), one at each neck. Nothing holds the front between the posts.

## What the sizes force

Measured by the sketch on the saved field (`runs/21_split_v3.txt`, `runs/22_split_v1.txt`):

- The front (lip, bone over the card, `front_low`, their films) is 380 mm wide with its posts: it is either cut in the middle or separated from its posts.
- A ring with its side bone fits only turned (273 to 284 mm). A ring with its post does not fit at all (313 to 315 mm, turned or not).
- A base rail is 316 mm: it is cut once. With the rear sweep the rear part fits easily (212 mm) and already has three pads.
- A post with the front part of the base rail is an L of 306 by 216 mm and does not fit; the post alone fits turned (226 mm).

So seven pieces is the least (front, two posts, two rings, two rears), and the front parts of the base rails make nine.

## Two layouts sketched

| | v1: the front cut in the middle | v3: the front whole |
|---|---|---|
| Pieces | 8: two front halves (each with its post), two rings, two rear pieces, and the base rails' front parts go with the front halves | 9: the front panel, two posts, two rings, two rail fronts, two rear pieces |
| The front's seam | one, at the connector's window (X 8): through the lip, the bone over the card, `front_low` and the hood over the I/O module | two, near the corners (X ±130): through the same three bones; the hood and the face stay whole |
| Bones cut by seams | 5 (3 in the middle, 2 base rails) | 8 (3 each side of the front, 2 base rails) |
| Largest piece | a front half: 291 x 286 x 206 turned, over 290 as sketched (it carries the rail's front part) | the front panel: 306 mm wide as sketched (286 with the seams at X ±130 on the surface, to be set), 273 turned |
| Pads a piece already has | front halves 2, rings 1, rears 3 | front panel 0, posts 1, rail fronts 2, rings 1, rears 3 |

Picture of v3: `pictures/split_v3_front_left.png`, `split_v3_front_right.png`, `split_v3_left.png` (blue the front panel, orange the posts, green the rings, magenta the rail fronts, red the rear pieces). The cuts in the picture are where the nearest bone changes owner; they are not designed joints.

## The decisions that are the owner's

1. **Where the front's seam goes:** one seam in the middle of the face (v1) or two near the corners (v3). The main session recommends v3: the face and the hood stay whole.
2. **How the pieces hold together.**
   - *Joined:* a screwed joint at every cut bone, so that the assembled layer is the body it is today, on today's twelve pads. The skeleton does not change. Costs: a joint design that prints (a half-lap with one M3 screw into an insert, in a thickened knot of the bone), about fourteen joints in v3, a check that a driver reaches each joint's screw, and the strength run reads the joints as rigid.
   - *Separate:* each piece on its own pads with a 3 mm gap to its neighbours, as the rear panel is. Costs: new pads and inserts in the skeleton (the rings have one pad each, the posts one, the front panel none), and the front still needs joints, because nothing stands behind it: a half of the lip that ends free is a 190 mm bar, about 34 MPa under the 30 N push by hand.
   - The main session recommends joined pieces, with the rear pieces left separate where three pads already hold them.

**Decided by the owner, 20 Nov 2026:** seams near the corners (the face and the hood whole), and the pieces screwed to each other. The skeleton and its twelve pads stay as they are.

## The joint: a first probe (20 Nov 2026)

`docs/plans/sketches/joint_probe.py` builds a half-lap by itself: a knot of radius 10 over a lap of 24 mm, parted by a plane through the bar's axis with 0.3 mm between the faces, a 3.4 mm clearance bore in one half and a blind 4.5 mm insert pilot in the other, on the layer's grid and through the layer's mesher (`shell_concepts.mesh`, which also smooths). What comes out (`runs/23_joint_probe.txt`):

| | Grid 1.5 mm (the layer's), two placements | Grid 0.75 mm |
|---|---|---|
| A lap face, asked at ±0.15 mm | mean within 0.06 mm of it, points from 0.01 to 0.27 mm off the parting plane | mean within 0.01 mm, points within 0.04 mm |
| The 3.4 mm bore | mean 3.0 to 3.1 mm, least 2.5 mm: an M3 screw does not pass | mean 3.37 mm, least 3.26 mm |
| The 4.5 mm pilot | mean 4.33 to 4.38 mm, from 3.7 to 4.9 mm | mean 4.46 mm, from 4.27 to 4.62 mm |

So the flat faces of a lap are good enough on the layer's grid, and its holes are not: they come out small and uneven, which `cables-and-organic.md` already says of the pads' bores ("the real holes belong in the printable pieces"). A piece that is meshed for printing at 0.75 mm gets holes an insert and a screw can use; a piece of at most 290 mm is 58 million points at that step, which fits in memory. That export step is needed whichever way the pieces hold together, for the pads' own bores.

## The joint: what others do, and a picture (20 Nov 2026)

Grok looked up joints between printed parts (printer makers' design guides, Stratasys on sectioned FDM tools, CNC Kitchen's insert tests, a PETG data sheet). Its answer, with the sources' limits:

- **A stepped half-lap pulled shut by a screw into an insert** is the joint to use. Stratasys prefers a lap for sectioned parts; a spigot, a dovetail or a butt joint needs a sliding fit of about 0.2 mm, which is less than this surface's error, so it would bind in one place and rattle in another, and a butt joint with a screw on the bar's axis does not resist bending until its faces touch.
- The faces the screw closes need no slip gap. Shoulders that must not meet first get about 0.5 mm (inferred, not tested). One screw is enough if the step has shoulders both ways; two stop it turning by themselves.
- Layers along the bar, the insert's hole vertical when printed. Bambu's PETG bends at 75 MPa in the layer plane and 56 MPa across the layers (one maker's sheet).
- The owner's insert is the short Voron kind: the maker's hole is 4.4 mm, the least wall about 1.3 mm (a reseller's copy of the maker's table). An M3 insert in PETG pulled out at about 119 kg in one maker's test, a longer insert than this one; the moment here asks about 20 to 30 kg of the screw (inferred). No source measured this insert in PETG, nor a half-lap in bending.

Picture: `pictures/split_joint_together.png` and `split_joint_apart.png`, one joint drawn on the lip at X 128 on a 0.75 mm grid: a knot of radius 10 over 36 mm (the bone there is about 5.5), a lap of 24 mm, an M3 from the front and above with its head sunk in the knot, the insert in the lower half. The loose shards beside it are film strands the picture's crude cut went through; the films are not laid for a seam yet.

## The second sketch: the layer built with its joints (20 Nov 2026)

`docs/plans/sketches/split_layer_sketch.py` loads `organic_frame`, replaces its `bone_members` and `film_list`, and builds the layer as it would be: a knot on every bone a seam crosses, no film across a seam. Nothing in `cad_b6/` is edited. Runs: `runs/24_split_layer.txt` (the build), `runs/25_split_pieces.txt` (the cut), `runs/26_split_strength.txt` (the strength run), `runs/27_split_drivers.txt` (the drivers' ways). Pictures: the pieces in colours, `pictures/split_pieces_front_left.png`, `split_pieces_front_right.png`, `split_pieces_left.png` (blue the front panel, green the corner pieces, orange the left foot and the right post, magenta the right rail's front, red the rear pieces); the look, `pictures/render_split_a_hero.png`, `render_split_a_front_left.png`, `render_split_a_front_right.png`.

**Eight pieces, not nine, and not the nine of v3.** The right ring's film lands on the front post, and a film may not hang between two pieces. So the top of each front post goes with its ring (a corner piece), and the post is cut at Z 150, below the film:

| Piece | What it is | Pads | Joints |
|---|---|---|---|
| `front` | the lip, the bone over the card and `front_low` between the front seams, their films, the hood | 0 | 6 |
| `corner_R`, `corner_L` | the ring, the side bone, the post above Z 150, the outer ends of the lip and of the bone over the card, the films and ties on them | 1 each (`neck_top`) | 4 and 5 |
| `foot_L` | the left post below Z 150, the outer end of `front_low`, the front of the base rail, the ring's tie to the rail | 2 | 4 |
| `post_R` | the right post below Z 150 with the outer end of `front_low` | 1 (`front_post_R`) | 2 |
| `rail_R` | the front of the right base rail | 1 (`front_foot_R`) | 1 |
| `rear_R`, `rear_L` | the rear sweep, the rest of the base rail, the film between them | 3 each | 2 each |

On the right the post's foot and the base rail do not join (known since revision 18: `front-and-outline.md`, "The front posts' feet hang"; measured again on today's field), so they are two pieces there. On the left they are one body.

**Thirteen joints.** Each is a knot of radius 10 over a lap of 20 mm (24 in the first picture), tapering to the bone over 8 mm each side, 36 mm in all:

| Joint | Where | The screw is driven from | Head in |
|---|---|---|---|
| `lip_L`, `lip_R` | the lip at X ±127 | the front and above (the board's normal) | `front` |
| `card_L`, `card_R` | the bone over the card at X ±127 | the same | `front` |
| `low_L`, `low_R` | `front_low` at X -127 and X 140 | the same | `front` |
| `post_L`, `post_R` | the front posts at Z 150 | the front | the corner piece |
| `rail_L`, `rail_R` | the base rails at Y 165 | the side | the rail's front |
| `sweep_L`, `sweep_R` | the rear sweeps, 24 mm from the ring | the side | the corner piece |
| `tie3_L` | the left ring's tie to the rail, 24 mm from the ring | the side | the corner piece |

All six joints of the front panel part across the same direction, so the panel goes on last, straight along the board's normal. The order on the skeleton: rear pieces, the rail's front and the feet, the corner pieces, the front panel; the piece that goes on later carries the head.

**What had to move for the joints.**

- The lip lies 3 mm under the radiator's edge (the layer keeps `GAP_HW` from it), so a knot round the lip's axis would lose its upper side. The lip's knots stand 7 mm lower along the board's u; built, the layer has 1.03 and 0.90 of their two halves (left), 1.09 and 0.95 (right).
- On the right the hood's roof ended at X 143 and the post stands at X 155: no room for a lap between them. The roof's centre line ends at X 104 instead of 117 (its cap 26 beyond; the cheek at X 117 is still under it), and the lap is X 130 to 150.
- The two films between the bone over the card and the lip are each an inner film (the front panel's) and an outer film of two strands (the corner piece's). The front film is hung between X -103 and 103 (it was ±150) with 9 strands and 8 cross-threads (13 and 12): between X 103 and the posts the front is open, because a strand there would run from `front_low`'s end (a foot piece) to the bone over the card (a corner piece).
- The right ring's film lands on the post above Z 172 and round its knee on to the leg up to the lip (it landed between Z 152 and 195).

**What the build shows.** `organic_frame`'s own checks pass. `main` is 1977.0 cm3 (2015.5 today: fewer strands, thirteen knots), 56 strands and 27 cross-threads made (63 and 36 today), 2 taken out as torn (one strand, and the cross-thread on it), none left torn. Cut at the joints, the pieces touch nowhere but in the laps, each is one body, and each has the pads it is meant to have. No voxel of the layer stands in a driver's way to any of the thirteen screws (a cylinder of the head's radius, 45 mm out from the knot), and neither does any skeleton part or piece of hardware (their exact solids cut with the same cylinders: all thirteen free). The hoses and the cables are not in that check. One voxel of `corner_L` in a lap is loose from the piece: the lap is cut here on the 1.5 mm grid by which side of the parting plane a voxel's centre is, and the export of a piece cuts it exactly.

**Fit on the bed (290 mm).** Every piece fits in more than one position:

| Piece | cm3 | Standing as on the case | Lying (the lowest position that fits) |
|---|---|---|---|
| `front` | 494.0 | 255 x 255 on the bed, 273 tall | on its back: 232 x 287, 179 tall; face down or up along Y: 273 x 286, 94 tall |
| `corner_R` | 325.0 | over (300 tall) | on its side: 284 x 284, 141 tall; on its back: 232 x 232, 248 tall |
| `corner_L` | 267.3 | over (321 tall) | on its side: 250 x 285, 141 tall; on its back: 232 x 231, 248 tall |
| `foot_L` | 89.8 | 174 x 176, 177 tall | on its side: 185 x 185, 122 tall |
| `post_R` | 48.9 | 47 x 48, 177 tall | 137 x 137, 46 tall |
| `rail_R` | 22.5 | 103 x 104, 36 tall | on its side: 110 x 109, 21 tall |
| `rear_R` | 352.0 | 172 x 171, 252 tall | on its side: 252 x 251, 87 tall |
| `rear_L` | 377.6 | 173 x 173, 252 tall | on its side: 252 x 231, 87 tall |

"On its back" is the board's normal up; a side is the span of the solid's voxel centres plus the cube's own width along it, at the best whole degree of turn. The tight ones are the front panel lying (287, 286) and the corner pieces on their sides (284, 285); each has a roomier position. Which position each piece is printed in is not decided: it sets where supports go and which way each lap's faces and each insert's hole lie.

**Strength of the joined layer** (`organic_strength.py`'s run of `main` on the sketch's field, the knots solid): largest stress 5.2 MPa (6.1 today), largest displacement 2.34 mm (2.62 today), own weight 0.25 MPa; the push on every strand and cross-thread, 81 of 81, at most 4.6 MPa and 0.98 mm (5.8 MPa and 0.67 mm today). It passes against the 10 MPa allowable. 760 s.

That run reads a joint as a solid knot. It does not prove the joints: a half of a lap at its root is a half disc of radius 10, whose section modulus across the parting plane is 0.19 R^3 = 191 mm3, about that of a round bone of radius 6.2 (the lip is 5.5 to 7, the rings 6.5), less the screw's hole. So by hand a joint is about as strong in bending as the bone it sits on, if the screw holds the halves shut. Whether it does (the insert in PETG, the clamp across the layers) no source measured, and the strength run cannot say: **one joint is to be printed and tried by hand before the pieces are printed.**

**Not in this sketch.** The holes (the bore, the head's recess, the insert's pilot: they belong in the 0.75 mm export of a piece); the gap at a lap's shoulders; a piece's strength while it is handled alone; the print position of each piece; where in the code a joint and a printable piece live.

## The trial joint (20 Nov 2026)

`docs/plans/sketches/joint_trial.py` makes one joint by itself to print and try by hand: the size the second sketch builds on the layer (bone radius 6, knot radius 10, lap 20, taper 8), each half with a 35 mm stub to hold it by, 69 mm long and about 9 cm3. It is meshed at 0.4 mm, with the layer's mesher. The head's half has a 3.4 mm bore and a 7.8 mm recess (the skeleton's counterbore for a head on its washer) that leaves 5 mm of plastic under the washer (what the layer's pads clamp, so the screw is the pads' M3 x 10 and goes 4.5 mm into the insert); the insert's half has the skeleton's pilot (4.5 mm, 6.7 deep, 3.3 mm of plastic under it). The faces the screw closes have no gap; a tongue's tip stands 0.5 mm off the other half's shoulder.

Measured on the meshes (`runs/28_joint_trial.txt`): the lap faces within 0.005 mm of the parting plane, the bore 3.40 mm (3.36 to 3.44), the recess 7.80 (7.73 to 7.85), the pilot 4.49 (4.44 to 4.53), its floor 6.70 deep, the tongues' tips at 9.50; each half one closed body, its triangles facing outward.

Three files in `out/trial/joint/` (not in the repository), the same two halves lying three ways, because a piece of the layer has up to six joints that point different ways and cannot lie well for all of them; picture `pictures/joint_trial.png` (blue, orange, grey):

- `joint_up.stl`: the lap's faces up, the screw upright. The best case.
- `joint_wall.stl`: the lap's faces upright, printed as walls, the screw lying.
- `joint_down.stl`: the lap's faces down, on supports. The worst case.

What the trial is to answer: whether the halves seat without filing in each position, whether the insert goes in straight and holds when the screw is tightened, whether the knot splits along its layers, and how the closed joint takes a bend by hand against a bare bone of the same size.

**The screws and inserts are in stock.** Thirteen joints take thirteen M3 x 10, washers and inserts more: M3 x 10 from 16 to 29 (the owner has 105, the model may use 84), washers 93 to 106 (380, 304), inserts 104 to 117 (220, 176); figures of today from `cad_b6/report_frame_v0.txt`.

## Not looked at yet

- The joint's holes and fits as printed (the first probe: holes need the 0.75 mm mesh), and a trial print of one joint.
- Print position and supports per piece; the bed check today stands a piece as built and turns it about the vertical only.
- The hoses and the cables in a driver's way to each joint's screw; the order the pieces go on, tried.
- Strength of each piece on its own (while it is handled).
- Where a joint and a printable piece live in `organic_frame.py` (today a piece is a body of its own on its own pads, 3 mm from the others), the fastener bill for thirteen more screws and inserts, and the checks and tests that go with them. Grok's map of that machinery (20 Nov 2026) is kept outside the repository because it quotes local paths; the main session read it in full.

## Waiting on the owner

The look of the joined layer, from the three renders: the front film narrower with open corners, the hood's roof 13 mm shorter on the right, thirteen knots. Nothing goes into `cad_b6/` before he has seen them.
