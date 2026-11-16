# External cables: the board's rear connectors and the card's video outputs

Status: found on 16 Nov 2026 after the owner raised it. Nothing built. The owner is choosing between the ways below.

## What the model shows

Both the board's rear connectors and the card's video outputs face the left flank (-X). Measured on the voxel grid of the model (skeleton, hardware, hoses, cables, organic layer), depth along -X to the first obstacle:

- **Board, rear connectors** (board edge X -122, u 148..307, n -4..41): 58 mm, then the left side fan (X -205..-180, u 120..260, n -42..98). The model's `io_zone` keep-out reserves 50 mm for plugs and stops 8 mm short of the fan.
- **Card, video outputs** (bracket at X -124, u 76..127, n 5..115): 3 mm, then `gpu_post`, a solid placeholder block (v -20..-5.5, u 73..146, n up to 108) that covers the whole bracket. Above it (n 110) 52 to 60 mm to the organic layer.
- **No way out.** The left flank is closed by the fan, the ring round it and the layer's threads.

## Can the left fan move? (search over the flank, 10 mm steps, 3 mm margin)

- **Up:** no. The 360's end, the visor arm that holds it and the CPU hoses are there.
- **Outwards:** no. From 6 mm on it meets the CPU hoses, which pass outside the fan.
- **Down by about 110 mm** (fan's lower corner at n -150 or lower, u 90..140): free and clear of both sets of connectors. The fan is then wholly below the board's plane.
- **Forward and down along the board by about 115 mm** (u0 near 0, n0 -20..-60): free and clear of the board's connectors, but 56 mm in front of the card's outputs.
- **The right fan has no mirrored place:** below the board on the right are the PSU's cables, in front are the card's hoses. It can only stand where it stands.

## Owner's direction so far (16 Nov 2026)

- **Card:** rebuild the post so the outputs are open; the gap to the wall should then let the cables bend and leave towards the rear.
- **Board:** see whether the fan can be raised to free the connectors, and raise the other one too for symmetry. The search above says it cannot.

## Ways open

1. **No side fans.** Both flanks become open windows in the organic layer; the left one gives access to the connectors. Symmetric. Main session's judgement, not computed: in an open case the radiators' air leaves through the flanks anyway.
2. **Both fans stay; the connectors go to a panel at the rear** on short extension leads.
3. **Asymmetric:** the right fan stays, the left one goes or drops below the board.

In every case `gpu_post` becomes a frame with an opening for the outputs, and the layer in front of the outputs moves out so that a DisplayPort plug with its bend (about 80 mm) fits and the cables can run to the rear.
