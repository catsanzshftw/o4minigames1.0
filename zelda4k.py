import math, random, sys, tkinter as tk, threading, subprocess, os
from dataclasses import dataclass

import pygame as pg

# ───────────────────────── constants ────────────────────────
TILE          = 32                 # px per tile
MAP_W, MAP_H  = 20, 15             # tiles per screen
def SCR_SIZE(): return (MAP_W*TILE, MAP_H*TILE+32)  # +32 for HUD
FPS           = 60

PLAYER_VEL    = 3                  # px/frame
ENEMY_VEL     = 2
SWING_CD_MS   = 300
SWING_DUR_MS  = 120
SWORD_LEN     = 18

# NES palette
GRASS_LGHT = ( 48,168,80); GRASS_DRK=(18,92,38)
BRICK      = (152,93,82); BRICK_MORT=(104,60,52)
LINK_GRN   = (48,140,40); LINK_SKIN=(252,188,176); LINK_FACE=(40,40,40)
OCTOROK    = (208,56,56); BOSS_COLOR=(160,32,240)
UI_BG      = (0,0,0); UI_FG=(255,255,255); GOLD=(252,232,132)

# ─────────────────────── helper textures ─────────────────────
def rnd_tex(base,accent,density=0.1):
    surf=pg.Surface((TILE,TILE)); surf.fill(base)
    for _ in range(int(TILE*TILE*density)):
        surf.set_at((random.randrange(TILE),random.randrange(TILE)),accent)
    return surf

def brick_tex():
    surf=pg.Surface((TILE,TILE)); surf.fill(BRICK)
    pg.draw.rect(surf,BRICK_MORT,(0,TILE//2-2,TILE,4))
    for c in (0,TILE//2): pg.draw.rect(surf,BRICK_MORT,(c-2,-2,4,TILE))
    return surf

TILE_GRASS=rnd_tex(GRASS_LGHT,GRASS_DRK)
TILE_WALL =brick_tex()

# ───────────────────────── sprite factory ────────────────────
def make_link(facing):
    s=pg.Surface((16,16),pg.SRCALPHA)
    pg.draw.rect(s,LINK_GRN,(4,8,8,8)); pg.draw.rect(s,LINK_SKIN,(4,2,8,6))
    for p in [(6,4),(10,4)]: s.set_at(p,LINK_FACE)
    pg.draw.line(s,LINK_FACE,(4,11),(11,11))
    dirs={'L':[(1,8),(4,7),(4,9)],'R':[(15,8),(12,7),(12,9)],
          'U':[(8,1),(6,4),(10,4)],'D':[(8,14),(6,11),(10,11)]}
    pg.draw.polygon(s,LINK_GRN,dirs[facing])
    return pg.transform.scale(s,(TILE//2,TILE//2))

def make_octorok():
    s=pg.Surface((16,16),pg.SRCALPHA)
    pg.draw.circle(s,OCTOROK,(8,8),6)
    pg.draw.rect(s,LINK_FACE,(5,5,2,2)); pg.draw.rect(s,LINK_FACE,(9,5,2,2))
    return pg.transform.scale(s,(TILE//2,TILE//2))

LINK_SURF={d:make_link(d) for d in 'UDLR'}
OCTO_SURF=make_octorok()

# ───────────────────────── HUD icons ───────────────────────
def draw_icon(shape,scale=1):
    if shape=='heart': pts=[(3,0),(5,0),(6,1),(6,3),(3,5),(0,3),(0,1),(1,0)]
    elif shape=='rupee': pts=[(4,0),(8,4),(8,8),(4,12),(0,8),(0,4)]
    elif shape=='key':
        s=pg.Surface((12*scale,8*scale),pg.SRCALPHA)
        pg.draw.rect(s,UI_FG,(0,3*scale,8*scale,2*scale))
        pg.draw.circle(s,UI_FG,(9*scale,4*scale),3*scale)
        return s
    elif shape=='bomb':
        s=pg.Surface((10*scale,10*scale),pg.SRCALPHA)
        pg.draw.circle(s,UI_FG,(5*scale,5*scale),4*scale)
        pg.draw.line(s,GOLD,(5*scale,1),(5*scale,-2),max(scale,1))
        return s
    else:
        pts = [(0,0)]
    s=pg.Surface((max(x for x,y in pts)*scale+1,max(y for x,y in pts)*scale+1),pg.SRCALPHA)
    pg.draw.polygon(s,GOLD if shape!='heart' else UI_FG,[(x*scale,y*scale) for x,y in pts])
    return s

RUPEE_ICON=draw_icon('rupee',2)
KEY_ICON=draw_icon('key',2)
BOMB_ICON=draw_icon('bomb',2)
HEART_FULL=draw_icon('heart',2)
HEART_EMPTY=draw_icon('heart',2)

# ─────────────────────── dataclasses ────────────────────────
@dataclass
class Entity:
    x:float; y:float; surf:pg.Surface
    @property
    def rect(self): return self.surf.get_rect(topleft=(self.x,self.y))
    def draw(self,screen): screen.blit(self.surf,(self.x,self.y))

class Player(Entity):
    def __init__(self,x,y):
        super().__init__(x,y,LINK_SURF['D'])
        self.dir='D'; self.last_swing=-SWING_CD_MS; self.hp=3; self.keys=0; self.rupees=0; self.bombs=0
    def handle_input(self):
        vel=pg.Vector2(0,0); keys=pg.key.get_pressed()
        dirs={'L':(-PLAYER_VEL,0),'R':(PLAYER_VEL,0),'U':(0,-PLAYER_VEL),'D':(0,PLAYER_VEL)}
        for k,d in [(pg.K_LEFT,'L'),(pg.K_a,'L'),(pg.K_RIGHT,'R'),(pg.K_d,'R'),(pg.K_UP,'U'),(pg.K_w,'U'),(pg.K_DOWN,'D'),(pg.K_s,'D')]:
            if keys[k]: vel+=pg.Vector2(dirs[d]); self.dir=d
        self.surf=LINK_SURF[self.dir]
        return vel

class Enemy(Entity):
    def __init__(self,x,y,surf,ai_dir): super().__init__(x,y,surf); self.dir=ai_dir

class Boss(Enemy):
    def __init__(self,x,y):
        surf = pg.Surface((TILE//2,TILE//2), pg.SRCALPHA)
        pg.draw.rect(surf, BOSS_COLOR, (0, 0, surf.get_width(), surf.get_height()))
        super().__init__(x, y, surf, pg.Vector2(0,0))
        self.hp=5

# ──────────────────────── World data ────────────────────────
WORLDS=[
    {'map':[[0]*MAP_W for _ in range(MAP_H)], 'boss_pos':(10*TILE,7*TILE)},
    {'map':[[random.choice([0,1,0,0]) for _ in range(MAP_W)] for _ in range(MAP_H)], 'boss_pos':(5*TILE,5*TILE)},
    {'map':[[1 if x%5==0 or y%4==0 else 0 for x in range(MAP_W)] for y in range(MAP_H)], 'boss_pos':(15*TILE,10*TILE)},
]

# ────────────────────────── Core Game ─────────────────────────
class Game:
    def __init__(self,world_idx=0):
        pg.init(); self.font=pg.font.SysFont('consolas',16,bold=True)
        self.world_idx=world_idx; self.load_world()
        self.screen=pg.display.set_mode(SCR_SIZE()); pg.display.set_caption(f'Zelda-Like: Dungeon {world_idx+1}')
        self.clock=pg.time.Clock(); self.run_flag=True

    def load_world(self):
        w=WORLDS[self.world_idx]
        self.map=w['map']; self.walls=[pg.Rect(x*TILE,y*TILE,TILE,TILE) for y,row in enumerate(self.map) for x,v in enumerate(row) if v]
        self.player=Player(2*TILE,2*TILE)
        self.enemies=[Enemy(random.choice([3,MAP_W-3])*TILE, random.choice([3,MAP_H-3])*TILE, OCTO_SURF, pg.Vector2(random.choice([-1,1]),0)) for _ in range(5)]
        self.boss=Boss(*w['boss_pos']); self.sword=None

    def run(self):
        while self.run_flag:
            self.clock.tick(FPS); self.handle(); self.update(); self.draw()
        pg.quit(); self.next_world()

    def handle(self):
        for ev in pg.event.get():
            if ev.type==pg.QUIT: self.run_flag=False
            if ev.type==pg.KEYDOWN and ev.key==pg.K_SPACE and pg.time.get_ticks()-self.player.last_swing>=SWING_CD_MS:
                self.spawn_sword()

    def spawn_sword(self):
        self.player.last_swing=pg.time.get_ticks(); pr=self.player.rect
        offs={'U':(pr.centerx-SWORD_LEN//2,pr.top-SWORD_LEN),'D':(pr.centerx-SWORD_LEN//2,pr.bottom),
              'L':(pr.left-SWORD_LEN,pr.centery-SWORD_LEN//2),'R':(pr.right,pr.centery-SWORD_LEN//2)}[self.player.dir]
        self.sword=pg.Rect(offs,(SWORD_LEN,SWORD_LEN))

    def update(self):
        vel=self.player.handle_input(); self.move(self.player,vel)
        # sword life
        if self.sword and pg.time.get_ticks()-self.player.last_swing>SWING_DUR_MS: self.sword=None
        # enemies
        for e in self.enemies[:]: self.move(e,e.dir*ENEMY_VEL,ai=True)
        # sword hits
        if self.sword:
            for e in self.enemies[:]:
                if e.rect.colliderect(self.sword): self.enemies.remove(e); self.player.rupees+=1
            if self.boss and self.boss.rect.colliderect(self.sword): self.boss.hp-=1; self.sword=None
            if self.boss and self.boss.hp<=0: self.boss=None

    def move(self,entity,vel,ai=False):
        rect=entity.rect
        for ax in (0,1):
            step=[0,0]; step[ax]=vel[ax]
            nxt=rect.move(step)
            if any(nxt.colliderect(w) for w in self.walls):
                if ai: entity.dir*=-1
            else:
                if ax==0: entity.x+=vel.x
                else:      entity.y+=vel.y
                rect=entity.rect

    def draw(self):
        self.screen.fill((0,0,0))
        # draw map
        for y,row in enumerate(self.map):
            for x,v in enumerate(row): self.screen.blit(TILE_WALL if v else TILE_GRASS,(x*TILE,y*TILE))
        # draw entities
        for e in self.enemies: e.draw(self.screen)
        if self.boss: self.boss.draw(self.screen)
        self.player.draw(self.screen)
        if self.sword: pg.draw.rect(self.screen,GOLD,self.sword)
        self.draw_hud(); pg.display.flip()

    def draw_hud(self):
        # HUD area
        pg.draw.rect(self.screen,UI_BG,(0,MAP_H*TILE,SCR_SIZE()[0],32))
        icons=[(RUPEE_ICON,self.player.rupees),(KEY_ICON,self.player.keys),(BOMB_ICON,self.player.bombs)]
        for i,(icon,val) in enumerate(icons):
            self.screen.blit(icon,(10+i*80,MAP_H*TILE+8))
            txt=self.font.render(f"{val:02}",False,UI_FG); self.screen.blit(txt,(32+i*80,MAP_H*TILE+8))
        # hearts & boss hp
        for i in range(5):
            hsurf=HEART_FULL if i<self.player.hp else HEART_EMPTY
            self.screen.blit(hsurf,(SCR_SIZE()[0]-150+i*26,MAP_H*TILE+6))
        if self.boss:
            bh=self.font.render(f"Boss HP: {self.boss.hp}",False,UI_FG)
            self.screen.blit(bh,(SCR_SIZE()[0]//2-50,MAP_H*TILE+6))

    def next_world(self):
        if self.boss is None and self.world_idx+1<len(WORLDS):
            Game(self.world_idx+1).run()
        else:
            print("All dungeons cleared!")

# ─────────────────── launcher & build ─────────────────
def build_game():
    script=os.path.abspath(sys.argv[0]); cmd=[sys.executable,'-m','PyInstaller','--onefile',script]
    subprocess.run(cmd); tk.messagebox.showinfo('Done','Executable in dist/')

if __name__=='__main__':
    root=tk.Tk(); root.title('Zelda-Like multi-dungeon')
    tk.Label(root,text='Select Dungeon',font=('Consolas',14,'bold')).pack(pady=10)
    for idx in range(len(WORLDS)):
        tk.Button(root,text=f'Dungeon {idx+1}',width=12,command=lambda i=idx: [root.destroy(), threading.Thread(target=lambda: Game(i).run()).start()]).pack(pady=2)
    tk.Button(root,text='Build',width=12,command=build_game).pack(pady=5)
    tk.Button(root,text='Quit',width=12,command=root.destroy).pack(pady=2)
    root.mainloop()
