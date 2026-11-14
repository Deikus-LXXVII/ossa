import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
import math
c=math.cos(math.radians(45))
L=305; W=244; B0=65; H=L*c  # board bottom edge height, projected height
fig,(a,b)=plt.subplots(1,2,figsize=(15,8))
def r(ax,x,y,w,h,col,t,**k):
    ax.add_patch(Rectangle((x,y),w,h,fc=col,ec="k",lw=1.5,**k)); ax.text(x+w/2,y+h/2,t,ha="center",va="center",fontsize=9)
# FRONT
r(a,-229,0,458,65,"#e08a3a","радиатор 420 (458), лежит слева направо\nверх вентиляторов = низ платы")
r(a,-122,B0,W,H,"#4f81bd","",alpha=.9)
a.text(0,B0+H-25,"плата ATX 244 шир., наклон 45° от нас\n(видна высота ~216 из 305)",ha="center",fontsize=8,color="w")
r(a,-35,B0+H-95,70,50,"#c0504d","CPU")
r(a,-140,B0+40,280,52,"#6aa84f","GPU 280 (на плате)")
r(a,-197,B0+H,394,55,"#a9cc6b","радиатор 360 (394), лежит над платой")
a.set_title("Вид спереди (смотрим на плату)"); a.set_xlim(-300,300); a.set_ylim(-20,420)
# SIDE
x0=150
a2=b
bx=[x0,x0+H,x0+H+8,x0+8]; by=[B0,B0+H,B0+H-8,B0-8]
a2.add_patch(Polygon(list(zip(bx,by)),fc="#4f81bd",ec="k")); a2.text(x0+H/2+25,B0+H/2-15,"плата 45°",rotation=45,color="w",fontsize=9)
r(a2,x0-138,0,138,65,"#e08a3a","420\n138×65")
r(a2,x0+H-121,B0+H,121,55,"#a9cc6b","360\n121×55")
# GPU perpendicular to board, mid
gx,gy=x0+H*0.45,B0+H*0.45; n=(-c,c); t=(c,c)
p=[(gx,gy),(gx+t[0]*51,gy+t[1]*51),(gx+t[0]*51+n[0]*148,gy+t[1]*51+n[1]*148),(gx+n[0]*148,gy+n[1]*148)]
a2.add_patch(Polygon(p,fc="#6aa84f",ec="k")); a2.text(gx-55,gy+60,"GPU",fontsize=9)
r(a2,x0+40,0,210,86,"#8e7cc3","БП? (под платой,\nсзади — уточнить)",alpha=.6)
a2.annotate("",xy=(x0,B0),xytext=(x0,0),arrowprops=dict(arrowstyle="-",ls="--"))
a2.set_title("Вид сбоку (перед слева)"); a2.set_xlim(-20,450); a2.set_ylim(-20,420)
for ax in (a,b): ax.set_aspect("equal"); ax.grid(alpha=.3)
fig.suptitle("Вариант B3, масштаб в мм")
plt.tight_layout(); plt.savefig("layout_b3.png",dpi=110)
