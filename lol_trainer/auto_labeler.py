"""
auto_labeler.py — Auto-anotação de screenshots usando o modelo treinado.
Usa o best.pt atual para gerar labels YOLO automaticamente nas novas imagens.
Uso: python auto_labeler.py
"""
import os
import sys
import shutil
import random
from pathlib import Path

# Config local do lol_trainer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (BASE_DIR, DATASET_DIR, INBOX_DIR, RUNS_DIR,
                    ORBWALKER_INBOX, YOLO_CLASSES, TrainDefaults)

try:
    from ultralytics import YOLO
except ImportError:
    print("[FATAL] ultralytics não instalado. Rode: pip install ultralytics")
    exit()

# ── Caminhos do dataset ──
DATASET_DIR  = Path(DATASET_DIR)
IMAGES_TRAIN = DATASET_DIR / "images" / "train"
IMAGES_VAL   = DATASET_DIR / "images" / "val"
LABELS_TRAIN = DATASET_DIR / "labels" / "train"
LABELS_VAL   = DATASET_DIR / "labels" / "val"
INBOX_DIR    = Path(INBOX_DIR)

# ── Modelo: best.pt do runs/ ──
MODEL_PATH = os.path.join(RUNS_DIR, "lol_orbwalker", "weights", "best.pt")

# Confiança mínima para aceitar uma detecção como label
CONFIDENCE_THRESHOLD = TrainDefaults.CONFIDENCE

# 80% treino, 20% validação
TRAIN_RATIO = 0.80

# Classes do YOLO
CLASS_NAMES = YOLO_CLASSES


def ensure_dirs():
    for d in [IMAGES_TRAIN, IMAGES_VAL, LABELS_TRAIN, LABELS_VAL, INBOX_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_inbox_images():
    """Retorna todas as imagens na pasta inbox que ainda não têm label."""
    exts = {".jpg", ".jpeg", ".png", ".bmp"}
    images = [p for p in INBOX_DIR.iterdir() if p.suffix.lower() in exts]
    return sorted(images)


def run_auto_label(model: YOLO, image_path: Path, confidence: float) -> list[str]:
    """
    Roda inferência na imagem e retorna as linhas de label no formato YOLO.
    Formato: class_id cx cy w h  (normalizado 0-1)
    """
    results = model(str(image_path), conf=confidence, verbose=False)
    
    lines = []
    for result in results:
        img_w = result.orig_shape[1]
        img_h = result.orig_shape[0]
        
        if result.boxes is None:
            continue
            
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf   = float(box.conf[0])
            
            # Coordenadas absolutas (x1, y1, x2, y2)
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            
            # Converter para formato YOLO (cx, cy, w, h normalizado)
            cx = ((x1 + x2) / 2) / img_w
            cy = ((y1 + y2) / 2) / img_h
            w  = (x2 - x1) / img_w
            h  = (y2 - y1) / img_h
            
            lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    
    return lines


def process_inbox(confidence: float = CONFIDENCE_THRESHOLD, dry_run: bool = False):
    """
    Processa todas as imagens na pasta inbox:
    1. Roda o modelo em cada uma
    2. Salva o .txt de label no formato YOLO
    3. Move imagem + label para train/ ou val/
    """
    images = get_inbox_images()
    
    if not images:
        print(f"\n[OK] Nenhuma imagem nova em: {INBOX_DIR}")
        print(f"     Coloque screenshots em: {INBOX_DIR}")
        return 0
    
    print(f"\n[>>] Carregando modelo: {MODEL_PATH}")
    if not os.path.exists(MODEL_PATH):
        print(f"[ERRO] Modelo não encontrado: {MODEL_PATH}")
        print("       Treine o modelo primeiro no trainer_ui.py")
        return 0
    
    model = YOLO(MODEL_PATH)
    
    print(f"[>>] Processando {len(images)} imagens (confiança >= {confidence:.0%})\n")
    
    labeled   = 0
    skipped   = 0
    
    for i, img_path in enumerate(images, 1):
        print(f"  [{i:3d}/{len(images)}] {img_path.name}", end="  ")
        
        # Gerar labels
        label_lines = run_auto_label(model, img_path, confidence)
        
        if not label_lines:
            print(f"→ Sem detecções — IGNORADA")
            skipped += 1
            continue
        
        # Contar por classe
        cls_counts = {}
        for line in label_lines:
            cid = int(line.split()[0])
            name = CLASS_NAMES.get(cid, str(cid))
            cls_counts[name] = cls_counts.get(name, 0) + 1
        
        summary = ", ".join(f"{v}x {k}" for k, v in cls_counts.items())
        print(f"→ {len(label_lines)} detecções [{summary}]")
        
        if dry_run:
            continue
        
        # Decidir se vai para train ou val
        split = "train" if random.random() < TRAIN_RATIO else "val"
        
        img_dest   = (IMAGES_TRAIN if split == "train" else IMAGES_VAL) / img_path.name
        label_dest = (LABELS_TRAIN if split == "train" else LABELS_VAL) / img_path.with_suffix(".txt").name
        
        # Copiar imagem
        shutil.copy2(img_path, img_dest)
        
        # Salvar label
        label_dest.write_text("\n".join(label_lines))
        
        # Remover da inbox
        img_path.unlink()
        
        labeled += 1
    
    print(f"\n{'─'*50}")
    print(f"  Anotadas:  {labeled}")
    print(f"  Ignoradas: {skipped} (sem detecções)")
    print(f"{'─'*50}")
    
    return labeled


def print_dataset_stats():
    """Imprime estatísticas do dataset atual."""
    print("\n── Dataset Stats ──────────────────────────────")
    
    for split in ["train", "val"]:
        img_dir = DATASET_DIR / "images" / split
        lbl_dir = DATASET_DIR / "labels" / split
        
        imgs   = list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png"))
        labels = list(lbl_dir.glob("*.txt"))
        
        # Contar por classe
        cls_counts = {name: 0 for name in CLASS_NAMES.values()}
        for lf in labels:
            for line in lf.read_text().splitlines():
                parts = line.strip().split()
                if parts:
                    cid = int(parts[0])
                    cls_counts[CLASS_NAMES.get(cid, str(cid))] += 1
        
        print(f"\n  [{split.upper()}]  {len(imgs)} imagens | {len(labels)} labels")
        for name, count in cls_counts.items():
            bar = "█" * min(count // 5, 40)
            print(f"    {name:<20} {count:4d}  {bar}")
    
    print(f"\n  [INBOX]  {len(get_inbox_images())} imagens aguardando")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    ensure_dirs()
    
    print("\n ╔═══════════════════════════════════════════╗")
    print(" ║   AUTO-LABELER — Anotação Automática      ║")
    print(" ║   Powered by YOLO best.pt                  ║")
    print(" ╚═══════════════════════════════════════════╝")
    
    print_dataset_stats()
    
    print(f"[INFO] Pasta inbox: {INBOX_DIR}")
    print(f"[INFO] Coloque screenshots novas na pasta inbox/ e rode este script.")
    print(f"[INFO] O modelo vai anotar tudo automaticamente.\n")
    
    inbox = get_inbox_images()
    if inbox:
        resp = input(f"  Processar {len(inbox)} imagens? [S/n]: ").strip().lower()
        if resp in ("", "s", "y"):
            process_inbox()
            print_dataset_stats()
    else:
        print(f"[OK] Inbox vazia. Adicione screenshots em:\n     {INBOX_DIR}\n")
