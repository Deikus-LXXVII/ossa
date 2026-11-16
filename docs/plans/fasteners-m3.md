# Fasteners: everything on M3 with captive nuts (Revision 12, planned)

Status: decided in the main session on 16 Nov 2026, not built. It starts after Revision 11 (the 420's bracket), because both change `cad_b6/frame_v0.py`.

## Why

The skeleton is drawn for ruthex heat-set inserts: about 58 M4 screws into 43 M4 and 20 short M4 inserts, and 34 M3 inserts for the board, the cable tie bridges and the organic layer. The owner has M3 socket head cap screws from 4 to 40 mm, about 700 M3 nuts, washers, at most 20 M3 inserts and no M4 screws (`docs/printer-and-materials.md`, "Fasteners on hand").

Three ways were weighed:

| Way | What it costs | Verdict |
|---|---|---|
| Buy M4 screws and all the inserts | a purchase, and about 110 inserts to melt in | the model stays as it is |
| M3 screws into M3 inserts | still a purchase of inserts; an M3 insert holds less than an M4 one | no gain |
| M3 screws into captive M3 nuts | a revision of every joint | chosen |

A steel nut in a pocket holds better in ABS than an insert, can be taken out and put back, and needs no soldering iron. The screws are not the weak part of any joint: the largest wall stress `strength.py` finds is in the plastic.

## Rules for the revision

- **One thread for the skeleton's own joints: M3.** Screw lengths only from the owner's table. The count of each length stays inside the kit with a fifth to spare, and the model checks that.
- **Captive nut:** a hex pocket for a 5.5 mm across-flats, 2.4 mm thick nut, with a slot that lets the nut slide in from a face that is reachable when the parts are assembled and that prints without support. The screw's hole runs on past the nut so that a screw never bottoms.
- **Heat-set inserts only under the board.** The owner has 20 M3 inserts at most. The nine board standoffs take them: a standoff is 6.35 mm tall and the screw comes from above into a blind boss, which is where a nut pocket is worst and an insert is best. That leaves eleven spare for ones that go in badly. Everything else (the cable tie bridges, the organic layer's pads, the drive sled, every joint of the skeleton) gets a nut.
- **Heads:** a washer under the head, or a counterbore where the head has to sit below the face. Sinking the head is also how a joint is brought to a length that is in the kit: the 26 joints through the 16 mm ribs go to M3 x 20 that way.
- **Screws that come with the hardware stay as they are:** 6-32 for the PSU, the radiators and a 3.5 inch drive, M3 for a 2.5 inch drive and the board. Where a printed wall is thicker than the stock screw allows (the 6 mm bulkhead under the PSU's screws), the wall gets a counterbore.
- **Side fans:** M3 x 35 through the 25 mm fan with a nut behind the bracket.
- Every existing check on holes, walls and fastener counts is kept and moved to the new hole kinds; none is dropped. `strength.py` is rerun, since nut slots take material out of the members' ends.

## Not covered by the owner's kits

- Twelve 6-32 screws about 35 mm long for the 420's fans, once the stock screw is measured (Revision 11).
- Anything the front I/O module needs, once it is measured.

## Update, 16 Nov 2026: the owner can order 100 more M3 inserts

With 20 on hand and 100 ordered there are 120 M3 inserts. The model needs about 97 (58 skeleton joints that are M4 or short M4 today, 9 under the board, 11 cable tie points, 12 pads of the organic layer, 2 for the drive sled, 2 for the front I/O, 3 to 5 for the side fans if they do not get a through screw and a nut).

Recommendation, main session: **order them, and keep inserts everywhere instead of nuts.** It is not strictly needed, nuts would work. The reasons to prefer inserts once there are enough of them:

- **The joints stay as they are drawn.** An insert pilot is a blind hole, as now; only its diameter and depth change from M4 to M3. A nut needs a pocket and a slot at every joint, which is a new shape at about 90 places, takes material out of the members' ends and has to be reachable and printable.
- **The owner's lengths fit without sinking any head.** With an M3 pilot 6.7 mm deep the stacks measured on the model give: 16 mm (26 joints) M3 x 20; 20 mm M3 x 25; 34 mm M3 x 40; 12 mm M3 x 16 or 18; 10 mm M3 x 14 or 16; 8 mm M3 x 12 or 14.
- **Assembly:** nothing to hold in place while a screw is started.

What it needs from the owner: the insert's outer diameter and length (of the ones on hand and of the ones ordered, best the same kind), because the pilot hole is sized to the insert. The model's M3 pilot today is 4.0 mm wide and 6.7 mm deep, which is ruthex's figure for its M3 x 5.7 insert.

If the owner does not order, the rules above (captive nuts, inserts only under the board) stand.

## Decided, 16 Nov 2026: M3 inserts everywhere

The owner orders 200 M3 inserts. Revision 12 is therefore the small one: every M4 and short M4 insert pilot becomes an M3 pilot, every M4 clearance hole an M3 one, the screw lengths come from the owner's table, and the model checks the count of each length and of the inserts against the stock. The captive-nut rules above are not used.

Open until the owner gives the insert's outer diameter and length: the pilot's diameter and depth.

**The 420's fan screws.** The owner's fan screws are about 30 mm under the head. With the 3 mm plate of Revision 11 the screws have to be about 33 mm; the nearest common length is 35 mm (6-32). Before ordering, the owner checks how deep a screw can go into the radiator's thread: a 35 mm screw goes 5 mm into it behind a 27 mm fan and the plate.
