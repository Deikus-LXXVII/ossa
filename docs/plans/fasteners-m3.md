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
