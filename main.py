import os
import math
import time
import copy
import threading
import tkinter as tk
from tkinter import messagebox, colorchooser

import glfw
from OpenGL.GL import *
from PIL import Image, ImageTk, ImageDraw, ImageFont


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEXTURES_DIR = os.path.join(BASE_DIR, "textures")
WEAPON_TEXTURES_DIR = os.path.join(BASE_DIR, "weapon_textures")
ENEMY_TEXTURES_DIR = os.path.join(BASE_DIR, "enemy_textures")


# ============================================================
# EDITOR CONFIG
# ============================================================

GRID_SIZE = 32.0

MIN_ZOOM = 0.15
MAX_ZOOM = 6.0

PLAYER_SIZE = 14.0


# ============================================================
# GAME CONFIG
# ============================================================

GAME_WIDTH = 1100
GAME_HEIGHT = 650

FOV = math.radians(70.0)

DEFAULT_PLAYER_SPEED = 170.0
DEFAULT_PLAYER_ROT_SPEED = 2.5

RAY_COUNT = 420
MAX_RAY_DISTANCE = 2000.0

WALL_HEIGHT = 64.0

PLAYER_MAX_LIVES = 100

WEAPON_DEFAULT_X = 0.0
WEAPON_HEIGHT = 250.0

SHOT_DURATION = 0.15
ENEMY_DEATH_DURATION = 0.35

ENEMY_MAX_RADIUS_CELLS = 15

# Урон одного выстрела.
PLAYER_SHOT_DAMAGE = 25

# Начальное HP стены.
DEFAULT_WALL_HEALTH = 100

# Скорость врага.
ENEMY_SPEED = 45.0

# Задержка между атаками врага.
ENEMY_ATTACK_COOLDOWN = 1.0


# ============================================================
# WORLD SETTINGS
# ============================================================

world_settings = {
    "sky_color": "#0e1320",
    "floor_color": "#19130d",
}


# ============================================================
# WORLD
# ============================================================

walls = []
enemies = []


player = {
    "x": 128.0,
    "y": 128.0,
    "angle": 0.0,

    "speed": DEFAULT_PLAYER_SPEED,

    # HP игрока.
    "lives": PLAYER_MAX_LIVES,

    "weapon_texture": "default_weapon.png",
    "attack_texture": "default_attack.png",

    "weapon_x": WEAPON_DEFAULT_X,

    # HUD HP.
    "health_text_color": "#ffffff",
    "health_text_x": 20,
    "health_text_y": 20,
}


# ============================================================
# GAME STATE
# ============================================================

game_running = False
game_stop_requested = False
game_thread = None

game_lock = threading.RLock()

game_snapshot = None


# ============================================================
# HELPERS
# ============================================================

def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def snap(value):
    return round(value / GRID_SIZE) * GRID_SIZE


def snap_point(x, y):
    return snap(x), snap(y)


def point_segment_distance(px, py, x1, y1, x2, y2):

    vx = x2 - x1
    vy = y2 - y1

    wx = px - x1
    wy = py - y1

    length_sq = vx * vx + vy * vy

    if length_sq < 0.000001:
        return distance(px, py, x1, y1)

    t = (wx * vx + wy * vy) / length_sq
    t = clamp(t, 0.0, 1.0)

    cx = x1 + vx * t
    cy = y1 + vy * t

    return distance(px, py, cx, cy)


def angle_difference(a, b):
    return (
        a - b + math.pi
    ) % (
        math.pi * 2
    ) - math.pi


def hex_to_rgb(value):
    value = value.lstrip("#")

    if len(value) != 6:
        return 0.1, 0.1, 0.1

    try:
        r = int(value[0:2], 16) / 255.0
        g = int(value[2:4], 16) / 255.0
        b = int(value[4:6], 16) / 255.0
        return r, g, b
    except Exception:
        return 0.1, 0.1, 0.1


# ============================================================
# SNAPSHOT
# ============================================================

def create_game_snapshot():

    with game_lock:
        return {
            "player": copy.deepcopy(player),
            "walls": copy.deepcopy(walls),
            "enemies": copy.deepcopy(enemies),
            "world_settings": copy.deepcopy(world_settings),
        }


def restore_game_snapshot(snapshot):

    if snapshot is None:
        return

    with game_lock:

        player.clear()
        player.update(
            copy.deepcopy(snapshot["player"])
        )

        walls.clear()
        walls.extend(
            copy.deepcopy(snapshot["walls"])
        )

        enemies.clear()
        enemies.extend(
            copy.deepcopy(snapshot["enemies"])
        )

        world_settings.clear()
        world_settings.update(
            copy.deepcopy(snapshot["world_settings"])
        )


# ============================================================
# TEXTURE DIRECTORIES
# ============================================================

def ensure_texture_directories():

    os.makedirs(TEXTURES_DIR, exist_ok=True)
    os.makedirs(WEAPON_TEXTURES_DIR, exist_ok=True)
    os.makedirs(ENEMY_TEXTURES_DIR, exist_ok=True)


# ============================================================
# TEXTURE SCAN
# ============================================================

def get_texture_files(
    directory,
    minimum_size=10,
    maximum_size=128
):

    os.makedirs(directory, exist_ok=True)

    result = []

    try:
        filenames = sorted(os.listdir(directory))
    except Exception:
        return result

    for filename in filenames:

        path = os.path.join(directory, filename)

        if not os.path.isfile(path):
            continue

        extension = os.path.splitext(filename)[1].lower()

        if extension not in (".png", ".jpg", ".jpeg"):
            continue

        try:

            with Image.open(path) as image:

                width, height = image.size

                if (
                    width < minimum_size
                    or height < minimum_size
                    or width > maximum_size
                    or height > maximum_size
                ):
                    continue

            result.append(filename)

        except Exception:
            pass

    return result


def get_wall_texture_files():
    return get_texture_files(TEXTURES_DIR, 10, 128)


def get_weapon_texture_files():
    return get_texture_files(
        WEAPON_TEXTURES_DIR,
        10,
        192
    )


def get_enemy_texture_files():
    return get_texture_files(
        ENEMY_TEXTURES_DIR,
        10,
        192
    )


# ============================================================
# DEFAULT TEXTURES
# ============================================================

def create_checker_texture(path, color1, color2):

    if os.path.exists(path):
        return path

    image = Image.new("RGB", (32, 32))
    pixels = image.load()

    for y in range(32):

        for x in range(32):

            if (x // 8 + y // 8) % 2 == 0:
                pixels[x, y] = color1
            else:
                pixels[x, y] = color2

    image.save(path)

    return path


def create_default_textures():

    ensure_texture_directories()

    wall_path = os.path.join(
        TEXTURES_DIR,
        "default.png"
    )

    weapon_path = os.path.join(
        WEAPON_TEXTURES_DIR,
        "default_weapon.png"
    )

    attack_path = os.path.join(
        WEAPON_TEXTURES_DIR,
        "default_attack.png"
    )

    enemy_path = os.path.join(
        ENEMY_TEXTURES_DIR,
        "default_enemy.png"
    )

    death_path = os.path.join(
        ENEMY_TEXTURES_DIR,
        "default_death.png"
    )

    create_checker_texture(
        wall_path,
        (160, 160, 160),
        (80, 80, 80)
    )

    # --------------------------------------------------------
    # WEAPON
    # --------------------------------------------------------

    if not os.path.exists(weapon_path):

        image = Image.new(
            "RGBA",
            (128, 128),
            (0, 0, 0, 0)
        )

        pixels = image.load()

        for y in range(40, 120):

            for x in range(40, 88):

                if 45 <= x <= 82 and 45 <= y <= 105:
                    pixels[x, y] = (
                        70,
                        70,
                        75,
                        255
                    )

        for y in range(20, 65):

            for x in range(55, 75):

                pixels[x, y] = (
                    100,
                    100,
                    105,
                    255
                )

        image.save(weapon_path)

    # --------------------------------------------------------
    # ATTACK
    # --------------------------------------------------------

    if not os.path.exists(attack_path):

        image = Image.new(
            "RGBA",
            (128, 128),
            (0, 0, 0, 0)
        )

        pixels = image.load()

        center_x = 64
        center_y = 50

        for y in range(10, 95):

            for x in range(10, 118):

                d = math.hypot(
                    x - center_x,
                    y - center_y
                )

                if d < 45:

                    alpha = int(
                        clamp(
                            255 - d * 4,
                            0,
                            255
                        )
                    )

                    pixels[x, y] = (
                        255,
                        190,
                        30,
                        alpha
                    )

        image.save(attack_path)

    # --------------------------------------------------------
    # ENEMY
    # --------------------------------------------------------

    if not os.path.exists(enemy_path):

        image = Image.new(
            "RGBA",
            (128, 128),
            (0, 0, 0, 0)
        )

        pixels = image.load()

        for y in range(20, 108):

            for x in range(20, 108):

                dx = x - 64
                dy = y - 64

                if dx * dx + dy * dy < 42 * 42:
                    pixels[x, y] = (
                        170,
                        45,
                        45,
                        255
                    )

        image.save(enemy_path)

    # --------------------------------------------------------
    # DEATH
    # --------------------------------------------------------

    if not os.path.exists(death_path):

        image = Image.new(
            "RGBA",
            (128, 128),
            (0, 0, 0, 0)
        )

        pixels = image.load()

        for y in range(35, 95):

            for x in range(20, 108):

                if abs(y - 65) < 10:

                    pixels[x, y] = (
                        100,
                        100,
                        100,
                        255
                    )

        image.save(death_path)

    return (
        wall_path,
        weapon_path,
        attack_path,
        enemy_path,
        death_path
    )


# ============================================================
# COLOR BUTTON HELPER
# ============================================================

def choose_color(parent, current, callback):

    color = colorchooser.askcolor(
        color=current,
        parent=parent
    )

    if color and color[1]:
        callback(color[1])


# ============================================================
# TEXTURE BROWSER
# ============================================================

class TextureBrowser:

    def __init__(
        self,
        parent,
        callback,
        directory,
        title,
        minimum_size,
        maximum_size
    ):

        self.parent = parent
        self.callback = callback
        self.directory = directory
        self.browser_title = title
        self.minimum_size = minimum_size
        self.maximum_size = maximum_size

        self.window = None
        self.images = []

    def open(self):

        if self.window is not None:

            try:

                if self.window.winfo_exists():
                    self.window.destroy()

            except Exception:
                pass

        self.window = tk.Toplevel(self.parent)

        self.window.title(self.browser_title)

        self.window.geometry("760x560")

        self.window.configure(bg="#17191d")

        self.window.transient(self.parent)

        tk.Label(
            self.window,
            text=self.browser_title.upper(),
            bg="#17191d",
            fg="#58c7ff",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=(12, 2))

        tk.Label(
            self.window,
            text=(
                "PNG / JPG / JPEG    "
                f"minimum {self.minimum_size}x{self.minimum_size}    "
                f"maximum {self.maximum_size}x{self.maximum_size}"
            ),
            bg="#17191d",
            fg="#9098a3",
            font=("Segoe UI", 9)
        ).pack(pady=(0, 10))

        outer = tk.Frame(
            self.window,
            bg="#17191d"
        )

        outer.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=8
        )

        canvas = tk.Canvas(
            outer,
            bg="#101216",
            highlightthickness=0
        )

        scrollbar = tk.Scrollbar(
            outer,
            orient="vertical",
            command=canvas.yview
        )

        canvas.configure(
            yscrollcommand=scrollbar.set
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )

        canvas.pack(
            side="left",
            fill="both",
            expand=True
        )

        content = tk.Frame(
            canvas,
            bg="#101216"
        )

        canvas.create_window(
            (0, 0),
            window=content,
            anchor="nw"
        )

        content.bind(
            "<Configure>",
            lambda event: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        textures = get_texture_files(
            self.directory,
            self.minimum_size,
            self.maximum_size
        )

        self.images.clear()

        if not textures:

            tk.Label(
                content,
                text=(
                    "No valid textures found.\n\n"
                    "Put textures into:\n"
                    f"{os.path.basename(self.directory)}/"
                ),
                bg="#101216",
                fg="#aaaaaa",
                font=("Segoe UI", 11)
            ).pack(
                padx=30,
                pady=50
            )

        else:

            columns = 4

            for index, filename in enumerate(textures):

                path = os.path.join(
                    self.directory,
                    filename
                )

                try:

                    image = Image.open(
                        path
                    ).convert("RGBA")

                    image.thumbnail(
                        (130, 130),
                        Image.Resampling.NEAREST
                    )

                    photo = ImageTk.PhotoImage(image)

                    self.images.append(photo)

                    frame = tk.Frame(
                        content,
                        bg="#20242a",
                        bd=1,
                        relief="solid"
                    )

                    frame.grid(
                        row=index // columns,
                        column=index % columns,
                        padx=8,
                        pady=8
                    )

                    tk.Label(
                        frame,
                        image=photo,
                        bg="#20242a",
                        width=135,
                        height=135
                    ).pack(
                        padx=5,
                        pady=5
                    )

                    tk.Button(
                        frame,
                        text=filename,
                        bg="#292e35",
                        fg="#eeeeee",
                        activebackground="#3c6680",
                        activeforeground="white",
                        relief="flat",
                        command=lambda name=filename:
                        self.select(name)
                    ).pack(
                        fill="x",
                        padx=5,
                        pady=(0, 5)
                    )

                except Exception as error:

                    print(
                        "Texture error:",
                        filename,
                        error
                    )

        tk.Button(
            self.window,
            text="CLOSE",
            command=self.window.destroy,
            bg="#292e35",
            fg="#eeeeee",
            activebackground="#3d5567",
            activeforeground="white",
            relief="flat",
            padx=20,
            pady=6
        ).pack(pady=10)

    def select(self, filename):

        self.callback(filename)

        if self.window is not None:

            try:
                self.window.destroy()
            except Exception:
                pass


# ============================================================
# PLAYER PROPERTIES
# ============================================================

class PlayerProperties:

    def __init__(self, editor):

        self.editor = editor
        self.window = None

        self.selected_weapon = None
        self.selected_attack = None

        self.health_color = player.get(
            "health_text_color",
            "#ffffff"
        )

    def open(self):

        if self.window is not None:

            try:

                if self.window.winfo_exists():
                    self.window.destroy()

            except Exception:
                pass

        self.window = tk.Toplevel(
            self.editor.root
        )

        self.window.title(
            "Player Properties"
        )

        self.window.geometry(
            "560x650"
        )

        self.window.configure(
            bg="#17191d"
        )

        self.window.transient(
            self.editor.root
        )

        tk.Label(
            self.window,
            text="PLAYER",
            bg="#17191d",
            fg="#58c7ff",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=(15, 15))

        form = tk.Frame(
            self.window,
            bg="#17191d"
        )

        form.pack(
            fill="x",
            padx=25
        )

        # SPEED

        tk.Label(
            form,
            text="Speed",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=8
        )

        self.speed_var = tk.DoubleVar(
            value=player["speed"]
        )

        tk.Spinbox(
            form,
            from_=10,
            to=1000,
            increment=5,
            textvariable=self.speed_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=0,
            column=1,
            padx=10
        )

        # HP

        tk.Label(
            form,
            text="Health / HP",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=8
        )

        self.health_var = tk.IntVar(
            value=clamp(
                player.get("lives", 100),
                1,
                1000
            )
        )

        tk.Spinbox(
            form,
            from_=1,
            to=1000,
            textvariable=self.health_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=1,
            column=1,
            padx=10
        )

        # WEAPON X

        tk.Label(
            form,
            text="Weapon X",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=8
        )

        self.weapon_x_var = tk.DoubleVar(
            value=player["weapon_x"]
        )

        tk.Spinbox(
            form,
            from_=-550,
            to=550,
            increment=1,
            textvariable=self.weapon_x_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=2,
            column=1,
            padx=10
        )

        # HEALTH TEXT COLOR

        tk.Label(
            form,
            text="Health Text Color",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=8
        )

        self.health_color_label = tk.Label(
            form,
            text=self.health_color,
            bg=self.health_color,
            fg="black",
            width=18
        )

        self.health_color_label.grid(
            row=3,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="CHOOSE",
            command=self.choose_health_color,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=3,
            column=2
        )

        # HEALTH TEXT X

        tk.Label(
            form,
            text="Health Text X",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=4,
            column=0,
            sticky="w",
            pady=8
        )

        self.health_x_var = tk.IntVar(
            value=player.get(
                "health_text_x",
                20
            )
        )

        tk.Spinbox(
            form,
            from_=0,
            to=GAME_WIDTH,
            textvariable=self.health_x_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=4,
            column=1,
            padx=10
        )

        # HEALTH TEXT Y

        tk.Label(
            form,
            text="Health Text Y",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=5,
            column=0,
            sticky="w",
            pady=8
        )

        self.health_y_var = tk.IntVar(
            value=player.get(
                "health_text_y",
                20
            )
        )

        tk.Spinbox(
            form,
            from_=0,
            to=GAME_HEIGHT,
            textvariable=self.health_y_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=5,
            column=1,
            padx=10
        )

        # WEAPON TEXTURE

        tk.Label(
            form,
            text="Weapon Texture",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=6,
            column=0,
            sticky="w",
            pady=8
        )

        self.weapon_label = tk.Label(
            form,
            text=player["weapon_texture"],
            bg="#252a31",
            fg="#8fd8ff",
            width=22,
            anchor="w"
        )

        self.weapon_label.grid(
            row=6,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="SELECT",
            command=self.select_weapon,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=6,
            column=2
        )

        # ATTACK TEXTURE

        tk.Label(
            form,
            text="Attack Texture",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=7,
            column=0,
            sticky="w",
            pady=8
        )

        self.attack_label = tk.Label(
            form,
            text=player["attack_texture"],
            bg="#252a31",
            fg="#8fd8ff",
            width=22,
            anchor="w"
        )

        self.attack_label.grid(
            row=7,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="SELECT",
            command=self.select_attack,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=7,
            column=2
        )

        buttons = tk.Frame(
            self.window,
            bg="#17191d"
        )

        buttons.pack(pady=25)

        tk.Button(
            buttons,
            text="APPLY",
            command=self.apply,
            bg="#1f7045",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

        tk.Button(
            buttons,
            text="CANCEL",
            command=self.window.destroy,
            bg="#713a3a",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

    def choose_health_color(self):

        choose_color(
            self.window,
            self.health_color,
            self.set_health_color
        )

    def set_health_color(self, color):

        self.health_color = color

        self.health_color_label.configure(
            text=color,
            bg=color
        )

    def select_weapon(self):

        TextureBrowser(
            self.editor.root,
            self.set_weapon,
            WEAPON_TEXTURES_DIR,
            "Weapon Texture",
            10,
            192
        ).open()

    def select_attack(self):

        TextureBrowser(
            self.editor.root,
            self.set_attack,
            WEAPON_TEXTURES_DIR,
            "Attack Texture",
            10,
            192
        ).open()

    def set_weapon(self, filename):

        self.weapon_label.configure(
            text=filename
        )

        self.selected_weapon = filename

    def set_attack(self, filename):

        self.attack_label.configure(
            text=filename
        )

        self.selected_attack = filename

    def apply(self):

        try:

            player["speed"] = clamp(
                float(self.speed_var.get()),
                10,
                1000
            )

            # Максимум 1000.
            player["lives"] = clamp(
                int(self.health_var.get()),
                1,
                1000
            )

            player["weapon_x"] = clamp(
                float(self.weapon_x_var.get()),
                -550,
                550
            )

            player["health_text_color"] = (
                self.health_color
            )

            player["health_text_x"] = clamp(
                int(self.health_x_var.get()),
                0,
                GAME_WIDTH
            )

            player["health_text_y"] = clamp(
                int(self.health_y_var.get()),
                0,
                GAME_HEIGHT
            )

            if self.selected_weapon is not None:
                player["weapon_texture"] = (
                    self.selected_weapon
                )

            if self.selected_attack is not None:
                player["attack_texture"] = (
                    self.selected_attack
                )

            self.window.destroy()

            self.editor.redraw()

        except Exception:

            messagebox.showerror(
                "Error",
                "Invalid player properties."
            )


# ============================================================
# ENEMY PROPERTIES
# ============================================================

class EnemyProperties:

    def __init__(self, editor, enemy_index):

        self.editor = editor
        self.enemy_index = enemy_index
        self.window = None

        self.selected_enemy_texture = None
        self.selected_death_texture = None

    def open(self):

        if (
            self.enemy_index < 0
            or self.enemy_index >= len(enemies)
        ):
            return

        enemy = enemies[self.enemy_index]

        self.window = tk.Toplevel(
            self.editor.root
        )

        self.window.title(
            "Enemy Properties"
        )

        self.window.geometry(
            "520x650"
        )

        self.window.configure(
            bg="#17191d"
        )

        self.window.transient(
            self.editor.root
        )

        tk.Label(
            self.window,
            text="ENEMY",
            bg="#17191d",
            fg="#ff7373",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=(15, 15))

        form = tk.Frame(
            self.window,
            bg="#17191d"
        )

        form.pack(
            fill="x",
            padx=25
        )

        # HP

        tk.Label(
            form,
            text="HP",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=8
        )

        self.hp_var = tk.IntVar(
            value=enemy.get("hp", 100)
        )

        tk.Spinbox(
            form,
            from_=1,
            to=99999,
            textvariable=self.hp_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=0,
            column=1,
            padx=10
        )

        # DAMAGE

        tk.Label(
            form,
            text="Damage",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=8
        )

        self.damage_var = tk.IntVar(
            value=enemy.get("damage", 10)
        )

        tk.Spinbox(
            form,
            from_=1,
            to=9999,
            textvariable=self.damage_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=1,
            column=1,
            padx=10
        )

        # AGGRO RADIUS

        tk.Label(
            form,
            text="Aggro Radius (cells)",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=8
        )

        self.radius_var = tk.IntVar(
            value=enemy.get(
                "radius_cells",
                5
            )
        )

        tk.Spinbox(
            form,
            from_=1,
            to=ENEMY_MAX_RADIUS_CELLS,
            textvariable=self.radius_var,
            width=12,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=2,
            column=1,
            padx=10
        )

        # CHASE

        tk.Label(
            form,
            text="Chase Player",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=8
        )

        self.chase_var = tk.BooleanVar(
            value=enemy.get(
                "chase",
                True
            )
        )

        tk.Checkbutton(
            form,
            text="CHASE / ATTACK",
            variable=self.chase_var,
            bg="#17191d",
            fg="#eeeeee",
            selectcolor="#252a31",
            activebackground="#17191d",
            activeforeground="white"
        ).grid(
            row=3,
            column=1,
            sticky="w",
            padx=10
        )

        # ENEMY TEXTURE

        tk.Label(
            form,
            text="Enemy Texture",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=4,
            column=0,
            sticky="w",
            pady=8
        )

        self.enemy_texture_label = tk.Label(
            form,
            text=enemy.get(
                "texture",
                "default_enemy.png"
            ),
            bg="#252a31",
            fg="#8fd8ff",
            width=24,
            anchor="w"
        )

        self.enemy_texture_label.grid(
            row=4,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="SELECT",
            command=self.select_enemy_texture,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=4,
            column=2
        )

        # DEATH TEXTURE

        tk.Label(
            form,
            text="Death Texture",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=5,
            column=0,
            sticky="w",
            pady=8
        )

        self.death_texture_label = tk.Label(
            form,
            text=enemy.get(
                "death_texture",
                "default_death.png"
            ),
            bg="#252a31",
            fg="#8fd8ff",
            width=24,
            anchor="w"
        )

        self.death_texture_label.grid(
            row=5,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="SELECT",
            command=self.select_death_texture,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=5,
            column=2
        )

        # DELETE

        tk.Button(
            self.window,
            text="DELETE ENEMY",
            command=self.delete_enemy,
            bg="#713a3a",
            fg="white",
            activebackground="#a74a4a",
            relief="flat",
            padx=30,
            pady=8
        ).pack(pady=(25, 8))

        buttons = tk.Frame(
            self.window,
            bg="#17191d"
        )

        buttons.pack(pady=5)

        tk.Button(
            buttons,
            text="APPLY",
            command=self.apply,
            bg="#1f7045",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

        tk.Button(
            buttons,
            text="CANCEL",
            command=self.window.destroy,
            bg="#292e35",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

    def select_enemy_texture(self):

        TextureBrowser(
            self.editor.root,
            self.set_enemy_texture,
            ENEMY_TEXTURES_DIR,
            "Enemy Texture",
            10,
            192
        ).open()

    def select_death_texture(self):

        TextureBrowser(
            self.editor.root,
            self.set_death_texture,
            ENEMY_TEXTURES_DIR,
            "Death Texture",
            10,
            192
        ).open()

    def set_enemy_texture(self, filename):

        self.enemy_texture_label.configure(
            text=filename
        )

        self.selected_enemy_texture = filename

    def set_death_texture(self, filename):

        self.death_texture_label.configure(
            text=filename
        )

        self.selected_death_texture = filename

    def apply(self):

        if (
            self.enemy_index < 0
            or self.enemy_index >= len(enemies)
        ):
            return

        enemy = enemies[self.enemy_index]

        try:

            enemy["hp"] = max(
                1,
                int(self.hp_var.get())
            )

            enemy["max_hp"] = enemy["hp"]

            enemy["damage"] = max(
                1,
                int(self.damage_var.get())
            )

            enemy["radius_cells"] = clamp(
                int(self.radius_var.get()),
                1,
                ENEMY_MAX_RADIUS_CELLS
            )

            enemy["chase"] = bool(
                self.chase_var.get()
            )

            if self.selected_enemy_texture is not None:
                enemy["texture"] = (
                    self.selected_enemy_texture
                )

            if self.selected_death_texture is not None:
                enemy["death_texture"] = (
                    self.selected_death_texture
                )

            self.window.destroy()

            self.editor.redraw()

        except Exception:

            messagebox.showerror(
                "Error",
                "Invalid enemy properties."
            )

    def delete_enemy(self):

        if (
            0 <= self.enemy_index
            < len(enemies)
        ):
            enemies.pop(self.enemy_index)

        self.window.destroy()

        self.editor.redraw()


# ============================================================
# WALL PROPERTIES
# ============================================================

class WallProperties:

    def __init__(self, editor, wall_index):

        self.editor = editor
        self.wall_index = wall_index
        self.window = None

        self.selected_texture = None

    def open(self):

        if (
            self.wall_index < 0
            or self.wall_index >= len(walls)
        ):
            return

        wall = walls[self.wall_index]

        self.window = tk.Toplevel(
            self.editor.root
        )

        self.window.title(
            "Wall Properties"
        )

        self.window.geometry(
            "500x420"
        )

        self.window.configure(
            bg="#17191d"
        )

        self.window.transient(
            self.editor.root
        )

        tk.Label(
            self.window,
            text="WALL",
            bg="#17191d",
            fg="#ffbd4a",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=(15, 15))

        form = tk.Frame(
            self.window,
            bg="#17191d"
        )

        form.pack(
            fill="x",
            padx=25
        )

        # HEALTH

        tk.Label(
            form,
            text="Health",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=10
        )

        self.health_var = tk.IntVar(
            value=max(
                1,
                int(
                    wall.get(
                        "health",
                        DEFAULT_WALL_HEALTH
                    )
                )
            )
        )

        tk.Spinbox(
            form,
            from_=1,
            to=999999,
            textvariable=self.health_var,
            width=14,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=0,
            column=1,
            padx=10
        )

        # MAX HEALTH

        tk.Label(
            form,
            text="Max Health",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=10
        )

        self.max_health_var = tk.IntVar(
            value=max(
                1,
                int(
                    wall.get(
                        "max_health",
                        wall.get(
                            "health",
                            DEFAULT_WALL_HEALTH
                        )
                    )
                )
            )
        )

        tk.Spinbox(
            form,
            from_=1,
            to=999999,
            textvariable=self.max_health_var,
            width=14,
            bg="#252a31",
            fg="white",
            insertbackground="white"
        ).grid(
            row=1,
            column=1,
            padx=10
        )

        # DMG

        tk.Label(
            form,
            text="DMG / Work DMG",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=10
        )

        self.dmg_var = tk.BooleanVar(
            value=wall.get(
                "work_dmg",
                False
            )
        )

        tk.Checkbutton(
            form,
            text="Wall can be damaged",
            variable=self.dmg_var,
            bg="#17191d",
            fg="#eeeeee",
            selectcolor="#252a31",
            activebackground="#17191d",
            activeforeground="white"
        ).grid(
            row=2,
            column=1,
            sticky="w",
            padx=10
        )

        # TEXTURE

        tk.Label(
            form,
            text="Texture",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=10
        )

        self.texture_label = tk.Label(
            form,
            text=wall.get(
                "texture",
                "default.png"
            ),
            bg="#252a31",
            fg="#8fd8ff",
            width=24,
            anchor="w"
        )

        self.texture_label.grid(
            row=3,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="SELECT",
            command=self.select_texture,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=3,
            column=2
        )

        # INFO

        tk.Label(
            self.window,
            text=(
                "Health is intentionally not displayed\n"
                "on the wall in the editor or game."
            ),
            bg="#17191d",
            fg="#777f8a",
            font=("Segoe UI", 9)
        ).pack(pady=15)

        buttons = tk.Frame(
            self.window,
            bg="#17191d"
        )

        buttons.pack(pady=10)

        tk.Button(
            buttons,
            text="APPLY",
            command=self.apply,
            bg="#1f7045",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

        tk.Button(
            buttons,
            text="DELETE WALL",
            command=self.delete_wall,
            bg="#713a3a",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

        tk.Button(
            buttons,
            text="CANCEL",
            command=self.window.destroy,
            bg="#292e35",
            fg="white",
            relief="flat",
            padx=25,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

    def select_texture(self):

        TextureBrowser(
            self.editor.root,
            self.set_texture,
            TEXTURES_DIR,
            "Wall Texture",
            10,
            128
        ).open()

    def set_texture(self, filename):

        self.texture_label.configure(
            text=filename
        )

        self.selected_texture = filename

    def apply(self):

        if (
            self.wall_index < 0
            or self.wall_index >= len(walls)
        ):
            return

        wall = walls[self.wall_index]

        try:

            max_health = max(
                1,
                int(self.max_health_var.get())
            )

            health = clamp(
                int(self.health_var.get()),
                1,
                max_health
            )

            wall["health"] = health
            wall["max_health"] = max_health

            wall["work_dmg"] = bool(
                self.dmg_var.get()
            )

            if self.selected_texture is not None:
                wall["texture"] = (
                    self.selected_texture
                )

            self.window.destroy()

            self.editor.redraw()

        except Exception:

            messagebox.showerror(
                "Error",
                "Invalid wall properties."
            )

    def delete_wall(self):

        if (
            0 <= self.wall_index
            < len(walls)
        ):
            walls.pop(self.wall_index)

        self.window.destroy()

        self.editor.redraw()


# ============================================================
# WORLD PROPERTIES
# ============================================================

class WorldProperties:

    def __init__(self, editor):

        self.editor = editor
        self.window = None

        self.sky_color = world_settings["sky_color"]
        self.floor_color = world_settings["floor_color"]

    def open(self):

        if self.window is not None:

            try:

                if self.window.winfo_exists():
                    self.window.destroy()

            except Exception:
                pass

        self.window = tk.Toplevel(
            self.editor.root
        )

        self.window.title(
            "World Settings"
        )

        self.window.geometry(
            "460x330"
        )

        self.window.configure(
            bg="#17191d"
        )

        self.window.transient(
            self.editor.root
        )

        tk.Label(
            self.window,
            text="WORLD SETTINGS",
            bg="#17191d",
            fg="#58c7ff",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=(20, 25))

        form = tk.Frame(
            self.window,
            bg="#17191d"
        )

        form.pack(
            fill="x",
            padx=30
        )

        # SKY

        tk.Label(
            form,
            text="Skybox Color",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=15
        )

        self.sky_label = tk.Label(
            form,
            text=self.sky_color,
            bg=self.sky_color,
            fg="white",
            width=18
        )

        self.sky_label.grid(
            row=0,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="CHOOSE",
            command=self.choose_sky,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=0,
            column=2
        )

        # FLOOR

        tk.Label(
            form,
            text="Floor Color",
            bg="#17191d",
            fg="#dddddd"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=15
        )

        self.floor_label = tk.Label(
            form,
            text=self.floor_color,
            bg=self.floor_color,
            fg="white",
            width=18
        )

        self.floor_label.grid(
            row=1,
            column=1,
            padx=10
        )

        tk.Button(
            form,
            text="CHOOSE",
            command=self.choose_floor,
            bg="#2b4e63",
            fg="white",
            relief="flat"
        ).grid(
            row=1,
            column=2
        )

        buttons = tk.Frame(
            self.window,
            bg="#17191d"
        )

        buttons.pack(pady=30)

        tk.Button(
            buttons,
            text="APPLY",
            command=self.apply,
            bg="#1f7045",
            fg="white",
            relief="flat",
            padx=30,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

        tk.Button(
            buttons,
            text="CANCEL",
            command=self.window.destroy,
            bg="#713a3a",
            fg="white",
            relief="flat",
            padx=30,
            pady=8
        ).pack(
            side="left",
            padx=5
        )

    def choose_sky(self):

        choose_color(
            self.window,
            self.sky_color,
            self.set_sky
        )

    def set_sky(self, color):

        self.sky_color = color

        self.sky_label.configure(
            text=color,
            bg=color
        )

    def choose_floor(self):

        choose_color(
            self.window,
            self.floor_color,
            self.set_floor
        )

    def set_floor(self, color):

        self.floor_color = color

        self.floor_label.configure(
            text=color,
            bg=color
        )

    def apply(self):

        world_settings["sky_color"] = self.sky_color
        world_settings["floor_color"] = self.floor_color

        self.window.destroy()

        self.editor.redraw()


# ============================================================
# EDITOR
# ============================================================

class Editor:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "Setkove Raycasting Engine"
        )

        self.root.geometry(
            "1250x850"
        )

        self.root.minsize(
            900,
            600
        )

        self.bg = "#111317"

        self.grid_color = "#252a31"
        self.major_grid_color = "#343b45"

        self.camera_x = 400.0
        self.camera_y = 300.0

        self.zoom = 1.0

        self.drawing_wall = False
        self.draw_start = None
        self.draw_current = None

        self.dragging_player = False
        self.dragging_enemy = None

        self.panning = False

        self.pan_last_x = 0
        self.pan_last_y = 0

        self.selected_wall = None
        self.selected_enemy = None

        self.last_right_click_time = 0.0
        self.last_right_click_world = None

        self.resize_job = None

        self.build_ui()

        self.create_default_map()

        self.redraw()

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        self.root.configure(
            bg=self.bg
        )

        toolbar = tk.Frame(
            self.root,
            bg="#17191d",
            height=55
        )

        toolbar.pack(
            side="top",
            fill="x"
        )

        tk.Label(
            toolbar,
            text="RAYCASTING LEVEL EDITOR",
            bg="#17191d",
            fg="#58c7ff",
            font=("Segoe UI", 16, "bold")
        ).pack(
            side="left",
            padx=16
        )

        tk.Button(
            toolbar,
            text="WORLD",
            command=self.open_world_properties,
            bg="#2b4e63",
            fg="white",
            activebackground="#3c6680",
            relief="flat",
            padx=15,
            pady=7
        ).pack(
            side="right",
            padx=5,
            pady=9
        )

        self.run_button = tk.Button(
            toolbar,
            text="RUN",
            command=self.run_game,
            bg="#1f7045",
            fg="white",
            activebackground="#2d9a61",
            relief="flat",
            padx=22,
            pady=7,
            font=("Segoe UI", 10, "bold")
        )

        self.run_button.pack(
            side="right",
            padx=5,
            pady=9
        )

        self.stop_button = tk.Button(
            toolbar,
            text="STOP",
            command=self.stop_game,
            bg="#8a3f3f",
            fg="white",
            activebackground="#b85454",
            relief="flat",
            padx=22,
            pady=7,
            font=("Segoe UI", 10, "bold")
        )

        self.stop_button.pack(
            side="right",
            padx=5,
            pady=9
        )

        tk.Button(
            toolbar,
            text="CLEAR WALLS",
            command=self.clear_walls,
            bg="#713a3a",
            fg="white",
            activebackground="#984848",
            relief="flat",
            padx=15,
            pady=7
        ).pack(
            side="right",
            padx=5,
            pady=9
        )

        center = tk.Frame(
            self.root,
            bg=self.bg
        )

        center.pack(
            fill="both",
            expand=True
        )

        self.canvas = tk.Canvas(
            center,
            bg=self.bg,
            highlightthickness=0,
            cursor="crosshair"
        )

        self.canvas.pack(
            fill="both",
            expand=True
        )

        self.canvas.bind(
            "<Button-1>",
            self.on_left_down
        )

        self.canvas.bind(
            "<B1-Motion>",
            self.on_left_drag
        )

        self.canvas.bind(
            "<ButtonRelease-1>",
            self.on_left_up
        )

        self.canvas.bind(
            "<Button-2>",
            self.on_middle_down
        )

        self.canvas.bind(
            "<B2-Motion>",
            self.on_middle_drag
        )

        self.canvas.bind(
            "<ButtonRelease-2>",
            self.on_middle_up
        )

        self.canvas.bind(
            "<Button-3>",
            self.on_right_click
        )

        self.canvas.bind(
            "<MouseWheel>",
            self.on_mouse_wheel
        )

        self.canvas.bind(
            "<Button-4>",
            self.on_mouse_wheel
        )

        self.canvas.bind(
            "<Button-5>",
            self.on_mouse_wheel
        )

        self.canvas.bind(
            "<Configure>",
            self.on_resize
        )

        tk.Label(
            self.root,
            text=(
                "LMB: draw wall / move player / move enemy    "
                "RMB: properties    "
                "RMB x2 empty: create enemy    "
                "MMB: pan    Wheel: zoom    "
                "WORLD: sky/floor    RUN / STOP / ESC"
            ),
            bg="#17191d",
            fg="#858d98",
            anchor="w",
            padx=12,
            pady=7
        ).pack(
            side="bottom",
            fill="x"
        )

    # ========================================================
    # DEFAULT MAP
    # ========================================================

    def create_default_map(self):

        with game_lock:

            walls.clear()
            enemies.clear()

            self.add_wall(0, 0, 1024, 0)
            self.add_wall(1024, 0, 1024, 640)
            self.add_wall(1024, 640, 0, 640)
            self.add_wall(0, 640, 0, 0)

            self.add_wall(256, 0, 256, 256)
            self.add_wall(256, 256, 512, 256)
            self.add_wall(512, 256, 512, 128)
            self.add_wall(640, 256, 1024, 256)
            self.add_wall(640, 256, 640, 512)

            player["x"] = 128.0
            player["y"] = 128.0
            player["angle"] = 0.0

    # ========================================================
    # COORDINATES
    # ========================================================

    def world_to_screen(self, x, y):

        width = max(
            1,
            self.canvas.winfo_width()
        )

        height = max(
            1,
            self.canvas.winfo_height()
        )

        sx = (
            x - self.camera_x
        ) * self.zoom + width / 2

        sy = (
            y - self.camera_y
        ) * self.zoom + height / 2

        return sx, sy

    def screen_to_world(self, x, y):

        width = max(
            1,
            self.canvas.winfo_width()
        )

        height = max(
            1,
            self.canvas.winfo_height()
        )

        wx = (
            x - width / 2
        ) / self.zoom + self.camera_x

        wy = (
            y - height / 2
        ) / self.zoom + self.camera_y

        return wx, wy

    # ========================================================
    # WALLS
    # ========================================================

    def add_wall(
        self,
        x1,
        y1,
        x2,
        y2,
        texture="default.png"
    ):

        if distance(x1, y1, x2, y2) < 3:
            return

        walls.append({
            "x1": float(x1),
            "y1": float(y1),
            "x2": float(x2),
            "y2": float(y2),

            "texture": texture,

            "health": DEFAULT_WALL_HEALTH,
            "max_health": DEFAULT_WALL_HEALTH,

            # По умолчанию стены НЕ разрушаются.
            "work_dmg": False
        })

    def find_wall(self, wx, wy):

        best = None

        tolerance = max(
            7,
            12 / self.zoom
        )

        best_distance = tolerance

        for index, wall in enumerate(walls):

            d = point_segment_distance(
                wx,
                wy,
                wall["x1"],
                wall["y1"],
                wall["x2"],
                wall["y2"]
            )

            if d < best_distance:

                best_distance = d
                best = index

        return best

    # ========================================================
    # ENEMIES
    # ========================================================

    def add_enemy(self, x, y):

        enemies.append({
            "x": float(x),
            "y": float(y),

            "hp": 100,
            "max_hp": 100,

            "damage": 10,

            "radius_cells": 5,

            # Новая настройка.
            "chase": True,

            "texture": "default_enemy.png",
            "death_texture": "default_death.png",

            "dead": False,
            "death_timer": 0.0,
            "attack_cooldown": 0.0
        })

    def find_enemy(self, wx, wy):

        best = None

        tolerance = max(
            10,
            18 / self.zoom
        )

        best_distance = tolerance

        for index, enemy in enumerate(enemies):

            d = distance(
                wx,
                wy,
                enemy["x"],
                enemy["y"]
            )

            if d < best_distance:

                best_distance = d
                best = index

        return best

    # ========================================================
    # PLAYER
    # ========================================================

    def is_player(self, wx, wy):

        radius = (
            PLAYER_SIZE * 2
        ) / self.zoom

        return (
            distance(
                wx,
                wy,
                player["x"],
                player["y"]
            ) <= radius
        )

    # ========================================================
    # LEFT MOUSE
    # ========================================================

    def on_left_down(self, event):

        if game_running:
            return

        wx, wy = self.screen_to_world(
            event.x,
            event.y
        )

        if self.is_player(wx, wy):

            self.dragging_player = True
            return

        enemy_index = self.find_enemy(wx, wy)

        if enemy_index is not None:

            self.dragging_enemy = enemy_index
            return

        wx, wy = snap_point(wx, wy)

        self.drawing_wall = True

        self.draw_start = (
            wx,
            wy
        )

        self.draw_current = (
            wx,
            wy
        )

        self.selected_wall = None
        self.selected_enemy = None

        self.redraw()

    def on_left_drag(self, event):

        if game_running:
            return

        wx, wy = self.screen_to_world(
            event.x,
            event.y
        )

        if self.dragging_player:

            wx, wy = snap_point(wx, wy)

            player["x"] = wx
            player["y"] = wy

            self.redraw()

            return

        if self.dragging_enemy is not None:

            wx, wy = snap_point(wx, wy)

            if (
                0 <= self.dragging_enemy
                < len(enemies)
            ):

                enemies[
                    self.dragging_enemy
                ]["x"] = wx

                enemies[
                    self.dragging_enemy
                ]["y"] = wy

            self.redraw()

            return

        if self.drawing_wall:

            wx, wy = snap_point(wx, wy)

            self.draw_current = (
                wx,
                wy
            )

            self.redraw()

    def on_left_up(self, event):

        if game_running:
            return

        if self.dragging_player:

            self.dragging_player = False
            self.redraw()
            return

        if self.dragging_enemy is not None:

            self.dragging_enemy = None
            self.redraw()
            return

        if not self.drawing_wall:
            return

        wx, wy = self.screen_to_world(
            event.x,
            event.y
        )

        wx, wy = snap_point(wx, wy)

        if self.draw_start:

            if distance(
                self.draw_start[0],
                self.draw_start[1],
                wx,
                wy
            ) >= 4:

                self.add_wall(
                    self.draw_start[0],
                    self.draw_start[1],
                    wx,
                    wy
                )

        self.drawing_wall = False
        self.draw_start = None
        self.draw_current = None

        self.redraw()

    # ========================================================
    # PAN
    # ========================================================

    def on_middle_down(self, event):

        self.panning = True

        self.pan_last_x = event.x
        self.pan_last_y = event.y

        self.canvas.configure(
            cursor="fleur"
        )

    def on_middle_drag(self, event):

        if not self.panning:
            return

        dx = event.x - self.pan_last_x
        dy = event.y - self.pan_last_y

        self.camera_x -= dx / self.zoom
        self.camera_y -= dy / self.zoom

        self.pan_last_x = event.x
        self.pan_last_y = event.y

        self.redraw()

    def on_middle_up(self, event):

        self.panning = False

        self.canvas.configure(
            cursor="crosshair"
        )

    # ========================================================
    # ZOOM
    # ========================================================

    def on_mouse_wheel(self, event):

        if hasattr(event, "delta") and event.delta != 0:

            direction = (
                1 if event.delta > 0
                else -1
            )

        elif getattr(event, "num", 0) == 4:

            direction = 1

        else:

            direction = -1

        before_x, before_y = (
            self.screen_to_world(
                event.x,
                event.y
            )
        )

        if direction > 0:
            self.zoom *= 1.15
        else:
            self.zoom /= 1.15

        self.zoom = clamp(
            self.zoom,
            MIN_ZOOM,
            MAX_ZOOM
        )

        after_x, after_y = (
            self.screen_to_world(
                event.x,
                event.y
            )
        )

        self.camera_x += (
            before_x - after_x
        )

        self.camera_y += (
            before_y - after_y
        )

        self.redraw()

    # ========================================================
    # RIGHT CLICK
    # ========================================================

    def on_right_click(self, event):

        if game_running:
            return

        wx, wy = self.screen_to_world(
            event.x,
            event.y
        )

        current_time = time.perf_counter()

        is_double = False

        if (
            self.last_right_click_world is not None
            and current_time -
            self.last_right_click_time < 0.45
        ):

            if distance(
                wx,
                wy,
                self.last_right_click_world[0],
                self.last_right_click_world[1]
            ) < 24 / self.zoom:

                is_double = True

        self.last_right_click_time = current_time

        self.last_right_click_world = (
            wx,
            wy
        )

        # PLAYER

        if self.is_player(wx, wy):

            PlayerProperties(self).open()
            return

        # ENEMY

        enemy_index = self.find_enemy(
            wx,
            wy
        )

        if enemy_index is not None:

            self.selected_enemy = enemy_index

            EnemyProperties(
                self,
                enemy_index
            ).open()

            return

        # WALL

        wall_index = self.find_wall(
            wx,
            wy
        )

        if wall_index is not None:

            self.selected_wall = wall_index

            WallProperties(
                self,
                wall_index
            ).open()

            return

        # CREATE ENEMY

        if is_double:

            ex, ey = snap_point(
                wx,
                wy
            )

            self.add_enemy(
                ex,
                ey
            )

            self.selected_enemy = (
                len(enemies) - 1
            )

            self.redraw()

    # ========================================================
    # WORLD
    # ========================================================

    def open_world_properties(self):

        if game_running:
            return

        WorldProperties(self).open()

    # ========================================================
    # CLEAR
    # ========================================================

    def clear_walls(self):

        if game_running:
            return

        walls.clear()

        self.selected_wall = None

        self.redraw()

    # ========================================================
    # GRID
    # ========================================================

    def draw_grid(self):

        self.canvas.delete("grid")

        width = max(
            1,
            self.canvas.winfo_width()
        )

        height = max(
            1,
            self.canvas.winfo_height()
        )

        left, top = self.screen_to_world(0, 0)
        right, bottom = self.screen_to_world(
            width,
            height
        )

        spacing = GRID_SIZE * self.zoom

        while spacing < 12:
            spacing *= 2

        while spacing > 100:
            spacing /= 2

        world_spacing = spacing / self.zoom

        start_x = (
            math.floor(left / world_spacing)
            * world_spacing
        )

        start_y = (
            math.floor(top / world_spacing)
            * world_spacing
        )

        x = start_x

        while x <= right + world_spacing:

            sx1, sy1 = self.world_to_screen(
                x,
                top
            )

            sx2, sy2 = self.world_to_screen(
                x,
                bottom
            )

            grid_index = round(
                x / GRID_SIZE
            )

            is_major = (
                abs(
                    x -
                    grid_index * GRID_SIZE
                ) < 0.001
            )

            color = (
                self.major_grid_color
                if is_major
                else self.grid_color
            )

            self.canvas.create_line(
                sx1,
                sy1,
                sx2,
                sy2,
                fill=color,
                width=1,
                tags="grid"
            )

            x += world_spacing

        y = start_y

        while y <= bottom + world_spacing:

            sx1, sy1 = self.world_to_screen(
                left,
                y
            )

            sx2, sy2 = self.world_to_screen(
                right,
                y
            )

            grid_index = round(
                y / GRID_SIZE
            )

            is_major = (
                abs(
                    y -
                    grid_index * GRID_SIZE
                ) < 0.001
            )

            color = (
                self.major_grid_color
                if is_major
                else self.grid_color
            )

            self.canvas.create_line(
                sx1,
                sy1,
                sx2,
                sy2,
                fill=color,
                width=1,
                tags="grid"
            )

            y += world_spacing

        # AXES

        sx1, sy1 = self.world_to_screen(
            left,
            0
        )

        sx2, sy2 = self.world_to_screen(
            right,
            0
        )

        self.canvas.create_line(
            sx1,
            sy1,
            sx2,
            sy2,
            fill="#663f3f",
            width=1,
            tags="grid"
        )

        sx1, sy1 = self.world_to_screen(
            0,
            top
        )

        sx2, sy2 = self.world_to_screen(
            0,
            bottom
        )

        self.canvas.create_line(
            sx1,
            sy1,
            sx2,
            sy2,
            fill="#3f6647",
            width=1,
            tags="grid"
        )

    # ========================================================
    # WALL DRAWING
    # ========================================================

    def draw_walls(self):

        self.canvas.delete("walls")

        for index, wall in enumerate(walls):

            x1, y1 = self.world_to_screen(
                wall["x1"],
                wall["y1"]
            )

            x2, y2 = self.world_to_screen(
                wall["x2"],
                wall["y2"]
            )

            if index == self.selected_wall:

                color = "#ffbd4a"

                line_width = max(
                    5,
                    7 * self.zoom
                )

            else:

                color = "#eeeeee"

                line_width = max(
                    3,
                    5 * self.zoom
                )

            self.canvas.create_line(
                x1,
                y1,
                x2,
                y2,
                fill=color,
                width=line_width,
                capstyle=tk.ROUND,
                tags="walls"
            )

            radius = max(
                3,
                4 * self.zoom
            )

            self.canvas.create_oval(
                x1 - radius,
                y1 - radius,
                x1 + radius,
                y1 + radius,
                fill=color,
                outline="",
                tags="walls"
            )

            self.canvas.create_oval(
                x2 - radius,
                y2 - radius,
                x2 + radius,
                y2 + radius,
                fill=color,
                outline="",
                tags="walls"
            )

    # ========================================================
    # PREVIEW
    # ========================================================

    def draw_preview(self):

        self.canvas.delete("preview")

        if not self.drawing_wall:
            return

        if self.draw_start is None:
            return

        if self.draw_current is None:
            return

        x1, y1 = self.world_to_screen(
            self.draw_start[0],
            self.draw_start[1]
        )

        x2, y2 = self.world_to_screen(
            self.draw_current[0],
            self.draw_current[1]
        )

        self.canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill="#4ec9ff",
            width=3,
            dash=(8, 5),
            capstyle=tk.ROUND,
            tags="preview"
        )

    # ========================================================
    # PLAYER DRAW
    # ========================================================

    def draw_player(self):

        self.canvas.delete("player")

        cx, cy = self.world_to_screen(
            player["x"],
            player["y"]
        )

        size = max(
            9,
            PLAYER_SIZE * self.zoom
        )

        angle = player["angle"]

        front_x = (
            cx +
            math.cos(angle) *
            size * 2
        )

        front_y = (
            cy +
            math.sin(angle) *
            size * 2
        )

        left_angle = (
            angle +
            math.radians(140)
        )

        right_angle = (
            angle -
            math.radians(140)
        )

        left_x = (
            cx +
            math.cos(left_angle) *
            size
        )

        left_y = (
            cy +
            math.sin(left_angle) *
            size
        )

        right_x = (
            cx +
            math.cos(right_angle) *
            size
        )

        right_y = (
            cy +
            math.sin(right_angle) *
            size
        )

        self.canvas.create_polygon(
            front_x,
            front_y,
            left_x,
            left_y,
            right_x,
            right_y,
            fill="#39a9e8",
            outline="#8bdcff",
            width=2,
            tags="player"
        )

    # ========================================================
    # ENEMY DRAW
    # ========================================================

    def draw_enemies(self):

        self.canvas.delete("enemy")

        for enemy in enemies:

            cx, cy = self.world_to_screen(
                enemy["x"],
                enemy["y"]
            )

            radius = max(
                7,
                12 * self.zoom
            )

            color = (
                "#777777"
                if enemy.get("dead", False)
                else "#d94c4c"
            )

            self.canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                fill=color,
                outline="#ffaaaa",
                width=2,
                tags="enemy"
            )

            if not enemy.get("dead", False):

                hp = max(
                    0,
                    enemy.get("hp", 100)
                )

                max_hp = max(
                    1,
                    enemy.get("max_hp", 100)
                )

                ratio = hp / max_hp

                bar_width = 28 * self.zoom

                self.canvas.create_rectangle(
                    cx - bar_width / 2,
                    cy - radius - 9,
                    cx + bar_width / 2,
                    cy - radius - 4,
                    fill="#301515",
                    outline="",
                    tags="enemy"
                )

                self.canvas.create_rectangle(
                    cx - bar_width / 2,
                    cy - radius - 9,
                    cx -
                    bar_width / 2 +
                    bar_width * ratio,
                    cy - radius - 4,
                    fill="#52d66d",
                    outline="",
                    tags="enemy"
                )

    # ========================================================
    # REDRAW
    # ========================================================

    def redraw(self):

        self.draw_grid()
        self.draw_walls()
        self.draw_enemies()
        self.draw_preview()
        self.draw_player()

        self.canvas.tag_raise("walls")
        self.canvas.tag_raise("enemy")
        self.canvas.tag_raise("preview")
        self.canvas.tag_raise("player")

    # ========================================================
    # RESIZE
    # ========================================================

    def on_resize(self, event):

        if self.resize_job is not None:

            try:
                self.root.after_cancel(
                    self.resize_job
                )
            except Exception:
                pass

        self.resize_job = self.root.after(
            60,
            self.redraw
        )

    # ========================================================
    # RUN
    # ========================================================

    def run_game(self):

        global game_running
        global game_stop_requested
        global game_thread
        global game_snapshot

        if game_running:
            return

        # Сохраняем абсолютно всё.
        game_snapshot = create_game_snapshot()

        game_stop_requested = False
        game_running = True

        self.run_button.configure(
            state="disabled"
        )

        self.stop_button.configure(
            state="normal"
        )

        game_thread = threading.Thread(
            target=game_loop,
            daemon=True
        )

        game_thread.start()

    # ========================================================
    # STOP
    # ========================================================

    def stop_game(self):

        global game_stop_requested

        if not game_running:
            return

        game_stop_requested = True


# ============================================================
# OPENGL TEXTURES
# ============================================================

gl_textures = {}


def load_gl_texture(path):

    if path in gl_textures:
        return gl_textures[path]

    try:

        image = Image.open(
            path
        ).convert("RGBA")

    except Exception as error:

        print(
            "Cannot load texture:",
            path,
            error
        )

        return None

    width, height = image.size

    texture = glGenTextures(1)

    glBindTexture(
        GL_TEXTURE_2D,
        texture
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_MIN_FILTER,
        GL_NEAREST
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_MAG_FILTER,
        GL_NEAREST
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_WRAP_S,
        GL_CLAMP_TO_EDGE
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_WRAP_T,
        GL_CLAMP_TO_EDGE
    )

    glPixelStorei(
        GL_UNPACK_ALIGNMENT,
        1
    )

    glTexImage2D(
        GL_TEXTURE_2D,
        0,
        GL_RGBA,
        width,
        height,
        0,
        GL_RGBA,
        GL_UNSIGNED_BYTE,
        image.tobytes()
    )

    glBindTexture(
        GL_TEXTURE_2D,
        0
    )

    gl_textures[path] = texture

    return texture


# ============================================================
# COLLISION
# ============================================================

def can_move_to(x, y, world_walls):

    radius = 10.0

    for wall in world_walls:

        d = point_segment_distance(
            x,
            y,
            wall["x1"],
            wall["y1"],
            wall["x2"],
            wall["y2"]
        )

        if d < radius:
            return False

    return True


# ============================================================
# RAYCAST
# ============================================================

def cast_ray(
    px,
    py,
    ray_dx,
    ray_dy,
    world_walls
):

    nearest = MAX_RAY_DISTANCE

    hit_wall = None
    hit_u = 0.0

    for wall in world_walls:

        x1 = wall["x1"]
        y1 = wall["y1"]

        x2 = wall["x2"]
        y2 = wall["y2"]

        sx = x2 - x1
        sy = y2 - y1

        denominator = (
            ray_dx * sy -
            ray_dy * sx
        )

        if abs(denominator) < 0.000001:
            continue

        dx = x1 - px
        dy = y1 - py

        t = (
            dx * sy -
            dy * sx
        ) / denominator

        if t <= 0:
            continue

        if t >= nearest:
            continue

        u = (
            dx * ray_dy -
            dy * ray_dx
        ) / denominator

        if u < 0.0 or u > 1.0:
            continue

        nearest = t
        hit_wall = wall
        hit_u = u

    return nearest, hit_wall, hit_u


# ============================================================
# TEXTURE PATHS
# ============================================================

def get_wall_texture_path(filename, default_path):

    if not filename:
        return default_path

    path = os.path.join(
        TEXTURES_DIR,
        filename
    )

    if not os.path.exists(path):
        return default_path

    return path


def get_weapon_texture_path(filename, default_path):

    if not filename:
        return default_path

    path = os.path.join(
        WEAPON_TEXTURES_DIR,
        filename
    )

    if not os.path.exists(path):
        return default_path

    return path


def get_enemy_texture_path(filename, default_path):

    if not filename:
        return default_path

    path = os.path.join(
        ENEMY_TEXTURES_DIR,
        filename
    )

    if not os.path.exists(path):
        return default_path

    return path


# ============================================================
# SHOOTING
# ============================================================

def get_shot_target(
    world_enemies,
    world_walls,
    player_x,
    player_y,
    player_angle
):

    # --------------------------------------------------------
    # Сначала находим ближайшую стену.
    # --------------------------------------------------------

    ray_dx = math.cos(player_angle)
    ray_dy = math.sin(player_angle)

    wall_distance, hit_wall, _ = cast_ray(
        player_x,
        player_y,
        ray_dx,
        ray_dy,
        world_walls
    )

    # --------------------------------------------------------
    # Затем проверяем врагов.
    # --------------------------------------------------------

    best_enemy = None
    best_enemy_distance = MAX_RAY_DISTANCE

    for enemy in world_enemies:

        if enemy.get("dead", False):
            continue

        dx = enemy["x"] - player_x
        dy = enemy["y"] - player_y

        dist = math.hypot(dx, dy)

        if dist < 1:
            continue

        enemy_angle = math.atan2(
            dy,
            dx
        )

        difference = abs(
            angle_difference(
                enemy_angle,
                player_angle
            )
        )

        # Небольшой размер hitbox врага.
        hit_angle = math.radians(5.5)

        if difference > hit_angle:
            continue

        if dist >= best_enemy_distance:
            continue

        # Проверяем стену между игроком и врагом.
        if wall_distance < dist:
            continue

        best_enemy = enemy
        best_enemy_distance = dist

    # --------------------------------------------------------
    # Если враг перед стеной — попали во врага.
    # Иначе попали в стену.
    # --------------------------------------------------------

    if best_enemy is not None:

        if best_enemy_distance < wall_distance:

            return (
                "enemy",
                best_enemy,
                best_enemy_distance
            )

    if hit_wall is not None:

        return (
            "wall",
            hit_wall,
            wall_distance
        )

    return (
        None,
        None,
        MAX_RAY_DISTANCE
    )


def shoot_enemy_or_wall(
    world_enemies,
    world_walls,
    player_x,
    player_y,
    player_angle
):

    target_type, target, target_distance = (
        get_shot_target(
            world_enemies,
            world_walls,
            player_x,
            player_y,
            player_angle
        )
    )

    if target_type == "enemy":

        target["hp"] -= PLAYER_SHOT_DAMAGE

        if target["hp"] <= 0:

            target["hp"] = 0

            target["dead"] = True

            target["death_timer"] = (
                ENEMY_DEATH_DURATION
            )

        return

    # --------------------------------------------------------
    # WALL DAMAGE
    # --------------------------------------------------------

    if target_type == "wall":

        wall = target

        # Только если включён Work DMG.
        if not wall.get(
            "work_dmg",
            False
        ):
            return

        wall["health"] = max(
            0,
            wall.get(
                "health",
                DEFAULT_WALL_HEALTH
            ) - PLAYER_SHOT_DAMAGE
        )

        if wall["health"] <= 0:

            try:
                world_walls.remove(wall)
            except ValueError:
                pass


# ============================================================
# SPRITE
# ============================================================

def draw_enemy_sprite(
    enemy,
    enemy_distance,
    relative_angle,
    focal_length,
    z_buffer,
    default_enemy_path,
    default_death_path
):

    if enemy_distance < 0.1:
        return

    screen_center = (
        GAME_WIDTH / 2
        +
        math.tan(relative_angle)
        *
        focal_length
    )

    sprite_height = (
        WALL_HEIGHT *
        focal_length /
        max(enemy_distance, 0.1)
        *
        1.7
    )

    sprite_width = (
        sprite_height *
        0.75
    )

    top = (
        GAME_HEIGHT / 2 -
        sprite_height / 2
    )

    bottom = (
        GAME_HEIGHT / 2 +
        sprite_height / 2
    )

    left = (
        screen_center -
        sprite_width / 2
    )

    right = (
        screen_center +
        sprite_width / 2
    )

    texture_name = enemy.get(
        "texture",
        "default_enemy.png"
    )

    is_dead = enemy.get(
        "dead",
        False
    )

    if is_dead:

        texture_name = enemy.get(
            "death_texture",
            "default_death.png"
        )

    texture_path = get_enemy_texture_path(
        texture_name,
        default_death_path
        if is_dead
        else default_enemy_path
    )

    texture = gl_textures.get(
        texture_path
    )

    if texture is None:

        texture = load_gl_texture(
            texture_path
        )

    if texture is None:
        return

    first_column = max(
        0,
        int(math.floor(left))
    )

    last_column = min(
        GAME_WIDTH - 1,
        int(math.ceil(right))
    )

    if first_column >= last_column:
        return

    visible_start = None
    visible_end = None

    glBindTexture(
        GL_TEXTURE_2D,
        texture
    )

    glColor4f(
        1.0,
        1.0,
        1.0,
        1.0
    )

    def flush_span(start, end):

        if start is None or end is None:
            return

        x1 = float(start)
        x2 = float(end + 1)

        tex_x1 = (
            x1 - left
        ) / max(
            right - left,
            1.0
        )

        tex_x2 = (
            x2 - left
        ) / max(
            right - left,
            1.0
        )

        glBegin(GL_QUADS)

        glTexCoord2f(
            tex_x1,
            0.0
        )

        glVertex2f(
            x1,
            top
        )

        glTexCoord2f(
            tex_x2,
            0.0
        )

        glVertex2f(
            x2,
            top
        )

        glTexCoord2f(
            tex_x2,
            1.0
        )

        glVertex2f(
            x2,
            bottom
        )

        glTexCoord2f(
            tex_x1,
            1.0
        )

        glVertex2f(
            x1,
            bottom
        )

        glEnd()

    for column in range(
        first_column,
        last_column + 1
    ):

        ray_index = int(
            column /
            GAME_WIDTH *
            RAY_COUNT
        )

        ray_index = int(
            clamp(
                ray_index,
                0,
                RAY_COUNT - 1
            )
        )

        visible = (
            enemy_distance <
            z_buffer[ray_index]
        )

        if visible:

            if visible_start is None:

                visible_start = column
                visible_end = column

            elif column == visible_end + 1:

                visible_end = column

            else:

                flush_span(
                    visible_start,
                    visible_end
                )

                visible_start = column
                visible_end = column

        else:

            if visible_start is not None:

                flush_span(
                    visible_start,
                    visible_end
                )

                visible_start = None
                visible_end = None

    if visible_start is not None:

        flush_span(
            visible_start,
            visible_end
        )


# ============================================================
# HUD TEXT
# ============================================================

hud_texture = None
hud_texture_key = None


def get_default_font(size=24):

    possible_paths = [
        os.path.join(
            BASE_DIR,
            "DejaVuSans.ttf"
        ),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for path in possible_paths:

        if os.path.exists(path):

            try:
                return ImageFont.truetype(
                    path,
                    size
                )
            except Exception:
                pass

    return ImageFont.load_default()


def create_hud_texture(text, color):

    global hud_texture
    global hud_texture_key

    key = (
        text,
        color
    )

    if hud_texture is not None and hud_texture_key == key:
        return hud_texture

    if hud_texture is not None:

        try:
            glDeleteTextures(
                [hud_texture]
            )
        except Exception:
            pass

        hud_texture = None

    font = get_default_font(24)

    dummy = Image.new(
        "RGBA",
        (8, 8),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(dummy)

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    width = max(
        8,
        bbox[2] - bbox[0] + 8
    )

    height = max(
        8,
        bbox[3] - bbox[1] + 8
    )

    image = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    rgb = hex_to_rgb(color)

    draw_color = (
        int(rgb[0] * 255),
        int(rgb[1] * 255),
        int(rgb[2] * 255),
        255
    )

    draw.text(
        (4, 2),
        text,
        font=font,
        fill=draw_color
    )

    hud_texture = glGenTextures(1)

    glBindTexture(
        GL_TEXTURE_2D,
        hud_texture
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_MIN_FILTER,
        GL_NEAREST
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_MAG_FILTER,
        GL_NEAREST
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_WRAP_S,
        GL_CLAMP_TO_EDGE
    )

    glTexParameteri(
        GL_TEXTURE_2D,
        GL_TEXTURE_WRAP_T,
        GL_CLAMP_TO_EDGE
    )

    glPixelStorei(
        GL_UNPACK_ALIGNMENT,
        1
    )

    glTexImage2D(
        GL_TEXTURE_2D,
        0,
        GL_RGBA,
        width,
        height,
        0,
        GL_RGBA,
        GL_UNSIGNED_BYTE,
        image.tobytes()
    )

    glBindTexture(
        GL_TEXTURE_2D,
        0
    )

    hud_texture_key = key

    return hud_texture


def draw_health_hud(
    lives,
    max_lives,
    x,
    y,
    color
):

    text = f"HP: {max(0, int(lives))}/{int(max_lives)}"

    texture = create_hud_texture(
        text,
        color
    )

    if texture is None:
        return

    # Размер текстуры заранее не нужен —
    # используем фиксированный размер HUD.
    width = 180
    height = 36

    glEnable(
        GL_TEXTURE_2D
    )

    glEnable(
        GL_BLEND
    )

    glBlendFunc(
        GL_SRC_ALPHA,
        GL_ONE_MINUS_SRC_ALPHA
    )

    glBindTexture(
        GL_TEXTURE_2D,
        texture
    )

    glColor4f(
        1.0,
        1.0,
        1.0,
        1.0
    )

    glBegin(GL_QUADS)

    glTexCoord2f(0.0, 0.0)
    glVertex2f(x, y)

    glTexCoord2f(1.0, 0.0)
    glVertex2f(x + width, y)

    glTexCoord2f(1.0, 1.0)
    glVertex2f(x + width, y + height)

    glTexCoord2f(0.0, 1.0)
    glVertex2f(x, y + height)

    glEnd()


# ============================================================
# GAME LOOP
# ============================================================

def game_loop():

    global game_running
    global game_stop_requested
    global game_snapshot
    global hud_texture
    global hud_texture_key

    window = None

    world_walls = []
    world_enemies = []

    try:

        # ====================================================
        # COPY WORLD
        # ====================================================

        with game_lock:

            world_walls = copy.deepcopy(
                walls
            )

            world_enemies = copy.deepcopy(
                enemies
            )

            start_player = copy.deepcopy(
                player
            )

            start_world = copy.deepcopy(
                world_settings
            )

        # ====================================================
        # DEFAULT TEXTURES
        # ====================================================

        (
            default_wall_path,
            default_weapon_path,
            default_attack_path,
            default_enemy_path,
            default_death_path
        ) = create_default_textures()

        # ====================================================
        # GLFW
        # ====================================================

        if not glfw.init():

            print(
                "GLFW initialization failed."
            )

            return

        window = glfw.create_window(
            GAME_WIDTH,
            GAME_HEIGHT,
            "Setkove Raycasting Engine",
            None,
            None
        )

        if not window:

            print(
                "Cannot create GLFW window."
            )

            return

        glfw.make_context_current(
            window
        )

        glfw.swap_interval(1)

        # ====================================================
        # OPENGL
        # ====================================================

        glViewport(
            0,
            0,
            GAME_WIDTH,
            GAME_HEIGHT
        )

        glMatrixMode(
            GL_PROJECTION
        )

        glLoadIdentity()

        glOrtho(
            0,
            GAME_WIDTH,
            GAME_HEIGHT,
            0,
            -1,
            1
        )

        glMatrixMode(
            GL_MODELVIEW
        )

        glLoadIdentity()

        glDisable(GL_DEPTH_TEST)

        glEnable(GL_TEXTURE_2D)

        glEnable(GL_BLEND)

        glBlendFunc(
            GL_SRC_ALPHA,
            GL_ONE_MINUS_SRC_ALPHA
        )

        glTexEnvi(
            GL_TEXTURE_ENV,
            GL_TEXTURE_ENV_MODE,
            GL_MODULATE
        )

        # ====================================================
        # TEXTURES
        # ====================================================

        load_gl_texture(
            default_wall_path
        )

        load_gl_texture(
            default_weapon_path
        )

        load_gl_texture(
            default_attack_path
        )

        load_gl_texture(
            default_enemy_path
        )

        load_gl_texture(
            default_death_path
        )

        for wall in world_walls:

            texture_path = get_wall_texture_path(
                wall.get(
                    "texture",
                    "default.png"
                ),
                default_wall_path
            )

            load_gl_texture(
                texture_path
            )

        for enemy in world_enemies:

            load_gl_texture(
                get_enemy_texture_path(
                    enemy.get(
                        "texture",
                        "default_enemy.png"
                    ),
                    default_enemy_path
                )
            )

            load_gl_texture(
                get_enemy_texture_path(
                    enemy.get(
                        "death_texture",
                        "default_death.png"
                    ),
                    default_death_path
                )
            )

        weapon_filename = start_player.get(
            "weapon_texture",
            "default_weapon.png"
        )

        attack_filename = start_player.get(
            "attack_texture",
            "default_attack.png"
        )

        weapon_x = start_player.get(
            "weapon_x",
            0.0
        )

        weapon_path = get_weapon_texture_path(
            weapon_filename,
            default_weapon_path
        )

        attack_path = get_weapon_texture_path(
            attack_filename,
            default_attack_path
        )

        load_gl_texture(weapon_path)
        load_gl_texture(attack_path)

        # ====================================================
        # CAMERA
        # ====================================================

        focal_length = (
            GAME_WIDTH / 2
        ) / math.tan(
            FOV / 2
        )

        column_width = (
            GAME_WIDTH /
            RAY_COUNT
        )

        # ====================================================
        # PLAYER
        # ====================================================

        px = start_player["x"]
        py = start_player["y"]

        player_angle = start_player["angle"]

        player_speed = start_player.get(
            "speed",
            DEFAULT_PLAYER_SPEED
        )

        max_lives = clamp(
            int(
                start_player.get(
                    "lives",
                    PLAYER_MAX_LIVES
                )
            ),
            1,
            1000
        )

        lives = max_lives

        health_text_color = start_player.get(
            "health_text_color",
            "#ffffff"
        )

        health_text_x = start_player.get(
            "health_text_x",
            20
        )

        health_text_y = start_player.get(
            "health_text_y",
            20
        )

        # ====================================================
        # WEAPON
        # ====================================================

        attack_timer = 0.0

        # ====================================================
        # TIMING
        # ====================================================

        last_time = time.perf_counter()

        # ====================================================
        # MAIN LOOP
        # ====================================================

        while not glfw.window_should_close(window):

            if game_stop_requested:
                break

            current_time = time.perf_counter()

            dt = min(
                current_time - last_time,
                0.033
            )

            last_time = current_time

            glfw.poll_events()

            # ------------------------------------------------
            # ESC
            # ------------------------------------------------

            if glfw.get_key(
                window,
                glfw.KEY_ESCAPE
            ) == glfw.PRESS:

                break

            # ------------------------------------------------
            # ROTATION
            # ------------------------------------------------

            if glfw.get_key(
                window,
                glfw.KEY_LEFT
            ) == glfw.PRESS:

                player_angle -= (
                    DEFAULT_PLAYER_ROT_SPEED *
                    dt
                )

            if glfw.get_key(
                window,
                glfw.KEY_RIGHT
            ) == glfw.PRESS:

                player_angle += (
                    DEFAULT_PLAYER_ROT_SPEED *
                    dt
                )

            # ------------------------------------------------
            # MOVEMENT
            # ------------------------------------------------

            forward = 0.0
            strafe = 0.0

            if glfw.get_key(
                window,
                glfw.KEY_W
            ) == glfw.PRESS:

                forward += 1.0

            if glfw.get_key(
                window,
                glfw.KEY_S
            ) == glfw.PRESS:

                forward -= 1.0

            if glfw.get_key(
                window,
                glfw.KEY_A
            ) == glfw.PRESS:

                strafe -= 1.0

            if glfw.get_key(
                window,
                glfw.KEY_D
            ) == glfw.PRESS:

                strafe += 1.0

            if forward != 0.0 or strafe != 0.0:

                length = math.hypot(
                    forward,
                    strafe
                )

                forward /= length
                strafe /= length

                move_speed = (
                    player_speed *
                    dt
                )

                cos_a = math.cos(
                    player_angle
                )

                sin_a = math.sin(
                    player_angle
                )

                dx = (
                    cos_a * forward -
                    sin_a * strafe
                ) * move_speed

                dy = (
                    sin_a * forward +
                    cos_a * strafe
                ) * move_speed

                new_x = px + dx
                new_y = py + dy

                if can_move_to(
                    new_x,
                    py,
                    world_walls
                ):

                    px = new_x

                if can_move_to(
                    px,
                    new_y,
                    world_walls
                ):

                    py = new_y

            # ------------------------------------------------
            # SHOOT
            # ------------------------------------------------

            if glfw.get_mouse_button(
                window,
                glfw.MOUSE_BUTTON_LEFT
            ) == glfw.PRESS:

                if attack_timer <= 0.0:

                    attack_timer = SHOT_DURATION

                    shoot_enemy_or_wall(
                        world_enemies,
                        world_walls,
                        px,
                        py,
                        player_angle
                    )

            if attack_timer > 0.0:

                attack_timer -= dt

            # ------------------------------------------------
            # ENEMY AI
            # ------------------------------------------------

            for enemy in world_enemies:

                if enemy.get(
                    "dead",
                    False
                ):

                    enemy["death_timer"] -= dt

                    continue

                enemy["attack_cooldown"] = max(
                    0.0,
                    enemy.get(
                        "attack_cooldown",
                        0.0
                    ) - dt
                )

                # --------------------------------------------
                # НОВОЕ:
                #
                # Chase=False -> враг вообще не преследует
                # игрока и не атакует его.
                # --------------------------------------------

                if not enemy.get(
                    "chase",
                    True
                ):
                    continue

                dx = px - enemy["x"]
                dy = py - enemy["y"]

                enemy_distance = math.hypot(
                    dx,
                    dy
                )

                radius_world = (
                    enemy.get(
                        "radius_cells",
                        5
                    )
                    *
                    GRID_SIZE
                )

                # Враг замечает игрока только внутри radius.
                if enemy_distance <= radius_world:

                    if enemy_distance > 35:

                        direction_x = (
                            dx /
                            max(
                                enemy_distance,
                                0.001
                            )
                        )

                        direction_y = (
                            dy /
                            max(
                                enemy_distance,
                                0.001
                            )
                        )

                        enemy_speed = (
                            ENEMY_SPEED *
                            dt
                        )

                        nx = (
                            enemy["x"] +
                            direction_x *
                            enemy_speed
                        )

                        ny = (
                            enemy["y"] +
                            direction_y *
                            enemy_speed
                        )

                        if can_move_to(
                            nx,
                            enemy["y"],
                            world_walls
                        ):

                            enemy["x"] = nx

                        if can_move_to(
                            enemy["x"],
                            ny,
                            world_walls
                        ):

                            enemy["y"] = ny

                    else:

                        if enemy[
                            "attack_cooldown"
                        ] <= 0:

                            lives -= enemy.get(
                                "damage",
                                10
                            )

                            lives = max(
                                0,
                                lives
                            )

                            enemy[
                                "attack_cooldown"
                            ] = ENEMY_ATTACK_COOLDOWN

            # =================================================
            # CLEAR
            # =================================================

            sky_r, sky_g, sky_b = hex_to_rgb(
                start_world.get(
                    "sky_color",
                    "#0e1320"
                )
            )

            floor_r, floor_g, floor_b = hex_to_rgb(
                start_world.get(
                    "floor_color",
                    "#19130d"
                )
            )

            glClearColor(
                sky_r,
                sky_g,
                sky_b,
                1.0
            )

            glClear(
                GL_COLOR_BUFFER_BIT
            )

            glLoadIdentity()

            # =================================================
            # SKY + FLOOR
            # =================================================

            glDisable(
                GL_TEXTURE_2D
            )

            # SKY

            glColor3f(
                sky_r,
                sky_g,
                sky_b
            )

            glBegin(GL_QUADS)

            glVertex2f(
                0,
                0
            )

            glVertex2f(
                GAME_WIDTH,
                0
            )

            glVertex2f(
                GAME_WIDTH,
                GAME_HEIGHT / 2
            )

            glVertex2f(
                0,
                GAME_HEIGHT / 2
            )

            # FLOOR

            glColor3f(
                floor_r,
                floor_g,
                floor_b
            )

            glVertex2f(
                0,
                GAME_HEIGHT / 2
            )

            glVertex2f(
                GAME_WIDTH,
                GAME_HEIGHT / 2
            )

            glVertex2f(
                GAME_WIDTH,
                GAME_HEIGHT
            )

            glVertex2f(
                0,
                GAME_HEIGHT
            )

            glEnd()

            # =================================================
            # RAYCAST
            # =================================================

            hits_by_texture = {}

            z_buffer = [
                MAX_RAY_DISTANCE
                for _ in range(RAY_COUNT)
            ]

            for ray_index in range(RAY_COUNT):

                camera_x = (
                    2.0 *
                    (
                        ray_index + 0.5
                    ) /
                    RAY_COUNT
                    -
                    1.0
                )

                ray_angle = (
                    player_angle +
                    camera_x *
                    FOV /
                    2.0
                )

                ray_dx = math.cos(
                    ray_angle
                )

                ray_dy = math.sin(
                    ray_angle
                )

                nearest, hit_wall, hit_u = (
                    cast_ray(
                        px,
                        py,
                        ray_dx,
                        ray_dy,
                        world_walls
                    )
                )

                if hit_wall is None:
                    continue

                corrected_distance = (
                    nearest *
                    math.cos(
                        ray_angle -
                        player_angle
                    )
                )

                corrected_distance = max(
                    corrected_distance,
                    0.1
                )

                z_buffer[
                    ray_index
                ] = corrected_distance

                wall_height = (
                    WALL_HEIGHT *
                    focal_length /
                    corrected_distance
                )

                top = (
                    GAME_HEIGHT / 2 -
                    wall_height / 2
                )

                bottom = (
                    GAME_HEIGHT / 2 +
                    wall_height / 2
                )

                brightness = clamp(
                    1.0 -
                    corrected_distance /
                    1800.0,
                    0.18,
                    1.0
                )

                texture_path = (
                    get_wall_texture_path(
                        hit_wall.get(
                            "texture",
                            "default.png"
                        ),
                        default_wall_path
                    )
                )

                if texture_path not in hits_by_texture:
                    hits_by_texture[
                        texture_path
                    ] = []

                screen_x = (
                    ray_index *
                    column_width
                )

                screen_x2 = (
                    screen_x +
                    column_width +
                    0.5
                )

                hits_by_texture[
                    texture_path
                ].append(
                    (
                        screen_x,
                        screen_x2,
                        top,
                        bottom,
                        hit_u,
                        brightness
                    )
                )

            # =================================================
            # WALLS
            # =================================================

            glEnable(
                GL_TEXTURE_2D
            )

            for texture_path, columns in (
                hits_by_texture.items()
            ):

                texture = gl_textures.get(
                    texture_path
                )

                if texture is None:

                    texture = load_gl_texture(
                        texture_path
                    )

                if texture is None:
                    continue

                glBindTexture(
                    GL_TEXTURE_2D,
                    texture
                )

                glBegin(GL_QUADS)

                for (
                    screen_x,
                    screen_x2,
                    top,
                    bottom,
                    tex_x,
                    brightness
                ) in columns:

                    glColor3f(
                        brightness,
                        brightness,
                        brightness
                    )

                    glTexCoord2f(
                        tex_x,
                        0.0
                    )

                    glVertex2f(
                        screen_x,
                        top
                    )

                    glTexCoord2f(
                        tex_x + 0.01,
                        0.0
                    )

                    glVertex2f(
                        screen_x2,
                        top
                    )

                    glTexCoord2f(
                        tex_x + 0.01,
                        1.0
                    )

                    glVertex2f(
                        screen_x2,
                        bottom
                    )

                    glTexCoord2f(
                        tex_x,
                        1.0
                    )

                    glVertex2f(
                        screen_x,
                        bottom
                    )

                glEnd()

            # =================================================
            # ENEMY SPRITES
            # =================================================

            visible_enemies = []

            for enemy in world_enemies:

                dx = enemy["x"] - px
                dy = enemy["y"] - py

                enemy_distance = math.hypot(
                    dx,
                    dy
                )

                if enemy_distance < 0.1:
                    continue

                angle_to_enemy = math.atan2(
                    dy,
                    dx
                )

                relative_angle = angle_difference(
                    angle_to_enemy,
                    player_angle
                )

                if abs(
                    relative_angle
                ) > (
                    FOV / 2 +
                    math.radians(15)
                ):
                    continue

                visible_enemies.append(
                    (
                        enemy_distance,
                        relative_angle,
                        enemy
                    )
                )

            visible_enemies.sort(
                reverse=True,
                key=lambda item: item[0]
            )

            for (
                enemy_distance,
                relative_angle,
                enemy
            ) in visible_enemies:

                draw_enemy_sprite(
                    enemy,
                    enemy_distance,
                    relative_angle,
                    focal_length,
                    z_buffer,
                    default_enemy_path,
                    default_death_path
                )

            # =================================================
            # WEAPON
            # =================================================

            glDisable(
                GL_DEPTH_TEST
            )

            glEnable(
                GL_BLEND
            )

            current_weapon_path = (
                attack_path
                if attack_timer > 0.0
                else weapon_path
            )

            weapon_texture = gl_textures.get(
                current_weapon_path
            )

            if weapon_texture is not None:

                glBindTexture(
                    GL_TEXTURE_2D,
                    weapon_texture
                )

                glColor4f(
                    1.0,
                    1.0,
                    1.0,
                    1.0
                )

                weapon_size = WEAPON_HEIGHT

                weapon_left = (
                    GAME_WIDTH / 2 -
                    weapon_size / 2 +
                    weapon_x
                )

                weapon_right = (
                    weapon_left +
                    weapon_size
                )

                weapon_top = (
                    GAME_HEIGHT -
                    weapon_size
                )

                weapon_bottom = GAME_HEIGHT

                glBegin(GL_QUADS)

                glTexCoord2f(
                    0.0,
                    0.0
                )

                glVertex2f(
                    weapon_left,
                    weapon_top
                )

                glTexCoord2f(
                    1.0,
                    0.0
                )

                glVertex2f(
                    weapon_right,
                    weapon_top
                )

                glTexCoord2f(
                    1.0,
                    1.0
                )

                glVertex2f(
                    weapon_right,
                    weapon_bottom
                )

                glTexCoord2f(
                    0.0,
                    1.0
                )

                glVertex2f(
                    weapon_left,
                    weapon_bottom
                )

                glEnd()

            # =================================================
            # CROSSHAIR
            # =================================================

            glDisable(
                GL_TEXTURE_2D
            )

            glColor3f(
                1.0,
                1.0,
                1.0
            )

            cross = 6

            glBegin(GL_LINES)

            glVertex2f(
                GAME_WIDTH / 2 - cross,
                GAME_HEIGHT / 2
            )

            glVertex2f(
                GAME_WIDTH / 2 + cross,
                GAME_HEIGHT / 2
            )

            glVertex2f(
                GAME_WIDTH / 2,
                GAME_HEIGHT / 2 - cross
            )

            glVertex2f(
                GAME_WIDTH / 2,
                GAME_HEIGHT / 2 + cross
            )

            glEnd()

            # =================================================
            # PLAYER HEALTH TEXT
            # =================================================

            draw_health_hud(
                lives,
                max_lives,
                health_text_x,
                health_text_y,
                health_text_color
            )

            # =================================================
            # GAME OVER
            # =================================================

            if lives <= 0:

                glDisable(
                    GL_TEXTURE_2D
                )

                glEnable(
                    GL_BLEND
                )

                glColor4f(
                    0.0,
                    0.0,
                    0.0,
                    0.65
                )

                glBegin(GL_QUADS)

                glVertex2f(
                    0,
                    0
                )

                glVertex2f(
                    GAME_WIDTH,
                    0
                )

                glVertex2f(
                    GAME_WIDTH,
                    GAME_HEIGHT
                )

                glVertex2f(
                    0,
                    GAME_HEIGHT
                )

                glEnd()

                glfw.swap_buffers(
                    window
                )

                time.sleep(0.7)

                break

            # =================================================
            # PRESENT
            # =================================================

            glfw.swap_buffers(
                window
            )

    except Exception as error:

        print(
            "\n================ GAME ERROR ================\n"
        )

        import traceback

        traceback.print_exc()

        print(
            "\n============================================\n"
        )

    finally:

        # ====================================================
        # RESTORE EDITOR
        # ====================================================

        try:

            restore_game_snapshot(
                game_snapshot
            )

        except Exception as error:

            print(
                "Snapshot restore error:",
                error
            )

        # ====================================================
        # OPENGL CLEANUP
        # ====================================================

        try:

            if window is not None:

                glfw.make_context_current(
                    window
                )

                if hud_texture is not None:

                    try:
                        glDeleteTextures(
                            [hud_texture]
                        )
                    except Exception:
                        pass

                    hud_texture = None
                    hud_texture_key = None

                glfw.destroy_window(
                    window
                )

        except Exception as error:

            print(
                "GLFW cleanup error:",
                error
            )

        try:

            glfw.terminate()

        except Exception:
            pass

        gl_textures.clear()

        game_running = False
        game_stop_requested = False
        game_snapshot = None


# ============================================================
# MAIN
# ============================================================

def main():

    global game_running
    global game_stop_requested

    ensure_texture_directories()

    create_default_textures()

    root = tk.Tk()

    editor = Editor(root)

    # ========================================================
    # MONITOR
    # ========================================================

    def monitor_game():

        if not root.winfo_exists():
            return

        if game_running:

            try:

                editor.run_button.configure(
                    state="disabled"
                )

                editor.stop_button.configure(
                    state="normal"
                )

            except Exception:
                pass

        else:

            try:

                editor.run_button.configure(
                    state="normal"
                )

                editor.stop_button.configure(
                    state="normal"
                )

                editor.redraw()

            except Exception:
                pass

        try:

            root.after(
                100,
                monitor_game
            )

        except Exception:
            pass

    root.after(
        100,
        monitor_game
    )

    # ========================================================
    # CLOSE
    # ========================================================

    closing = {
        "value": False
    }

    def on_close():

        global game_stop_requested

        if closing["value"]:
            return

        if game_running:

            closing["value"] = True

            game_stop_requested = True

            def wait_for_game():

                if game_running:

                    try:

                        root.after(
                            50,
                            wait_for_game
                        )

                    except Exception:
                        pass

                else:

                    try:
                        root.destroy()
                    except Exception:
                        pass

            root.after(
                50,
                wait_for_game
            )

        else:

            closing["value"] = True

            try:
                root.destroy()
            except Exception:
                pass

    root.protocol(
        "WM_DELETE_WINDOW",
        on_close
    )

    root.mainloop()




if __name__ == "__main__":
    main()
