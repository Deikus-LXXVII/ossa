import math, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.transforms as T
def box(ax,x,y,w,h,c,t,ang=0,tc="k",fs=9):
    r=Rectangle((x,y),w,h,fc=c,ec="k",lw=1.2)
    r.set_transform(T.Affine2D().rotate_deg_around(x,y,ang)+ax.transData); ax.add_patch(r)
    a=math.radians(ang); cx=x+w/2*math.cos(a)-h/2*math.sin(a); cy=y+w/2*math.sin(a)+h/2*math.cos(a)
    rot=ang+(90 if h>w*1.5 else 0)
    ax.text(cx,cy,t,ha="center",va="center",fontsize=fs,rotation=rot,color=tc)
    return cx,cy
fig,ax=plt.subplots(figsize=(13,9))
# side view: x = depth along board, y = height
box(ax,0,0,458,65,"#e08a3c","радиатор 420 лежит горизонтально, вдоль платы (458×65)")
ang=45; bx,by=60,85
# board 305 long, 20 thick, tilted 45°
box(ax,bx,by,305,20,"#4a7fb5","плата ATX под 45° (305)",ang=ang,tc="w")
a=math.radians(ang)
# CPU block on top face of board, at ~40% along
px=bx+120*math.cos(a)-20*math.sin(a); py=by+120*math.sin(a)+20*math.cos(a)
box(ax,px,py,60,35,"#c0504d","CPU",ang=ang,fs=8)
# GPU in slot, at ~70% along, perpendicular-ish to board (sticks out from board face)
gx=bx+200*math.cos(a)-20*math.sin(a); gy=by+200*math.sin(a)+20*math.cos(a)
box(ax,gx,gy,51,148,"#6aa84f","GPU",ang=ang,fs=8)
# PSU under board (in triangle space)
box(ax,140,70,210,86,"#8e7cc3","БП под платой (210×86)",tc="w")
# 360 rad vertical above board
box(ax,235,360,80,394,"#a4c86a","радиатор 360 + Noctua стоит вертикально (394×80)")
# tubes
ax.plot([px+10,300],[py+30,65],ls="--",color="#c0504d",lw=2)
ax.plot([gx-60,235],[gy+60,470],ls="--",color="#2e6b1f",lw=2)
ax.text(470,30,"← обдув вверх",fontsize=9)
ax.text(-60,760,"Вид сбоку, реальный масштаб, мм. Пунктир: трубки (CPU 500, GPU 450).",fontsize=10)
ax.set_aspect("equal"); ax.set_xlim(-80,620); ax.set_ylim(-30,790); ax.grid(alpha=.25)
ax.set_title("Вариант B2: 420 снизу, плата под 45°, 360 вертикально сверху, БП под платой",fontsize=12)
plt.tight_layout(); plt.savefig("layout_b2.png",dpi=100)
