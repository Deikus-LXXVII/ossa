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

## Not looked at yet

- The joint itself (its size, where its screw goes, whether a 1.5 mm grid prints a fit).
- The films that hang between bones of two pieces: the right ring's film to the post, the left ring's ties to the post and to the rail, the outer strands of the films over the card. Each either moves to one piece or becomes a joint.
- Print orientation and supports per piece; the bed check today stands a piece as built and turns it about the vertical only.
- Strength of each piece on its own (while it is handled) and of the joined layer.
- Grok's map of the machinery a piece goes through (pads, checks, manifests, strength, budgets) is being written; it goes here when it lands.
