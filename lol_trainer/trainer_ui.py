"""
trainer_ui.py — Interface DearPyGui PRO para treinar modelos YOLOv8.
Exibe gráficos de evolução em tempo real, métricas detalhadas e log completo.
Uso: python trainer_ui.py
"""
import threading
import subprocess
import shutil
import os
import sys
import re
import time

# Config local do lol_trainer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (BASE_DIR, DATASET_YAML, RUNS_DIR,
                    ORBWALKER_MODELS_DIR, TrainDefaults)
from auto_labeler import process_inbox, get_inbox_images, ensure_dirs, INBOX_DIR

try:
    import dearpygui.dearpygui as dpg
except ImportError:
    print("[FATAL] DearPyGui não está instalado! Rode: pip install dearpygui")
    exit()

RUNS_DIR = os.path.join(BASE_DIR, "runs", "detect")

# ── Regex para parsear output do YOLO ──
# Linha de treino:  "     50/150      3.02G    0.7835    0.8412     1.247       114       640:  ..."
TRAIN_LINE_RE = re.compile(
    r"\s*(\d+)/(\d+)\s+"           # epoch/total
    r"[\d.]+G?\s+"                 # GPU mem
    r"([\d.]+)\s+"                 # box_loss
    r"([\d.]+)\s+"                 # cls_loss
    r"([\d.]+)"                    # dfl_loss
)

# Linha de validação:  "                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95)"
# Seguida de:          "                   all        148        826      0.727      0.689      0.735      0.454"
VAL_METRICS_RE = re.compile(
    r"\s*all\s+\d+\s+\d+\s+"
    r"([\d.]+)\s+"                 # Precision
    r"([\d.]+)\s+"                 # Recall
    r"([\d.]+)\s+"                 # mAP50
    r"([\d.]+)"                    # mAP50-95
)


class TrainerUI:
    def __init__(self):
        self._training_active = False
        self._process = None
        self._start_time = None
        
        # ── Dados dos gráficos ──
        self._epochs = []
        self._box_loss = []
        self._cls_loss = []
        self._dfl_loss = []
        self._map50 = []
        self._map50_95 = []
        self._precision = []
        self._recall = []
        self._current_epoch = 0
        self._total_epochs = 0
        
        dpg.create_context()
        self._build_theme()
        self._build_ui()
        
        # ── Viewport ──
        dpg.create_viewport(title='YOLO Neural Trainer Pro', width=980, height=720, 
                           resizable=True, decorated=True)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("Main", True)
        dpg.start_dearpygui()
        dpg.destroy_context()

    def _build_ui(self):
        with dpg.window(tag="Main"):
            
            # ════════════ HEADER ════════════
            with dpg.group(horizontal=True):
                dpg.add_text("YOLO", color=(255, 140, 0))
                dpg.add_text("Neural Trainer", color=(200, 200, 200))
                dpg.add_text("   |   ", color=(60, 60, 60))
                dpg.add_text("Orbwalker Vision Suite", color=(80, 80, 80))
            
            dpg.add_spacer(height=2)
            
            # ════════════ STATUS BAR ════════════
            with dpg.group(horizontal=True):
                dpg.add_text("[", color=(60, 60, 60))
                dpg.add_text("IDLE", tag="lbl_state", color=(100, 100, 100))
                dpg.add_text("]", color=(60, 60, 60))
                dpg.add_text("", tag="lbl_progress", color=(150, 150, 150))
                dpg.add_text("", tag="lbl_eta", color=(80, 80, 80))
            
            dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=-1, height=4)
            dpg.add_spacer(height=4)
            
            # ════════════ MAIN LAYOUT: Left Config + Right Graphs ════════════
            with dpg.group(horizontal=True):
                
                # ──── LEFT PANEL: Config ────
                with dpg.child_window(width=280, height=-1, border=True):
                    dpg.add_text("CONFIGURACAO", color=(255, 140, 0))
                    dpg.add_separator()
                    
                    dpg.add_spacer(height=5)
                    # Detectar best.pt existente para permitir continuar treino
                    _best_pt = os.path.join(RUNS_DIR, "lol_orbwalker", "weights", "best.pt")
                    _model_items = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt"]
                    _model_default = "yolov8s.pt"
                    if os.path.exists(_best_pt):
                        _model_items = [_best_pt] + _model_items
                        _model_default = _best_pt
                    dpg.add_combo(
                        items=_model_items,
                        default_value=_model_default, label="Modelo", tag="yolo_model", width=200
                    )
                    # Indicador do modelo selecionado
                    _model_hint = ">> Continuando treino anterior" if os.path.exists(_best_pt) else "Treino do zero"
                    _hint_color = (100, 255, 100) if os.path.exists(_best_pt) else (150, 150, 150)
                    dpg.add_text(_model_hint, tag="lbl_model_hint", color=_hint_color)
                    
                    dpg.add_spacer(height=3)
                    dpg.add_slider_int(label="Epochs", default_value=150, 
                                      min_value=10, max_value=500, tag="yolo_epochs", width=140)
                    dpg.add_slider_int(label="ImgSize", default_value=416, 
                                      min_value=320, max_value=640, tag="yolo_imgsz", width=140)
                    dpg.add_slider_int(label="Batch", default_value=16, 
                                      min_value=1, max_value=64, tag="yolo_batch", width=140)
                    dpg.add_input_text(label="Name", default_value="lol_orbwalker", 
                                      tag="yolo_name", width=140)
                    
                    dpg.add_spacer(height=5)
                    dpg.add_separator()
                    dpg.add_text("AUTO-LABELING", color=(255, 140, 0))
                    dpg.add_checkbox(label="Label inbox antes de treinar",
                                    default_value=True, tag="chk_autolabel")
                    dpg.add_slider_float(label="Min. Conf.", default_value=0.40,
                                        min_value=0.10, max_value=0.90, 
                                        tag="label_conf", width=140, format="%.2f")
                    dpg.add_text("Checando inbox...", tag="lbl_inbox_count", color=(100, 100, 100))
                    
                    dpg.add_spacer(height=8)
                    dpg.add_separator()
                    dpg.add_spacer(height=5)
                    
                    # Botões
                    dpg.add_button(label="INICIAR TREINAMENTO", tag="btn_train", 
                                 width=-1, height=35, callback=self.start_training)
                    dpg.add_spacer(height=3)
                    dpg.add_button(label="PARAR", tag="btn_stop",
                                 width=-1, height=25, callback=self.stop_training, enabled=False)
                    
                    dpg.add_spacer(height=10)
                    dpg.add_separator()
                    dpg.add_text("METRICAS AO VIVO", color=(255, 140, 0))
                    dpg.add_separator()
                    dpg.add_spacer(height=5)
                    
                    # Métricas numéricas
                    with dpg.table(header_row=True, borders_innerH=False, borders_outerH=False,
                                  borders_innerV=True, borders_outerV=False):
                        dpg.add_table_column(label="Metrica", width_fixed=True, init_width_or_weight=100)
                        dpg.add_table_column(label="Valor", width_fixed=True, init_width_or_weight=80)
                        
                        for name, tag, color in [
                            ("Box Loss", "val_box", (255, 100, 100)),
                            ("Cls Loss", "val_cls", (100, 180, 255)),
                            ("DFL Loss", "val_dfl", (100, 255, 180)),
                            ("Precision", "val_prec", (255, 220, 100)),
                            ("Recall", "val_rec", (220, 100, 255)),
                            ("mAP50", "val_map50", (255, 180, 0)),
                            ("mAP50-95", "val_map95", (0, 255, 180)),
                        ]:
                            with dpg.table_row():
                                dpg.add_text(name, color=color)
                                dpg.add_text("---", tag=tag, color=(180, 180, 180))
                    
                    dpg.add_spacer(height=8)
                    dpg.add_separator()
                    dpg.add_spacer(height=3)
                    dpg.add_text("", tag="lbl_time", color=(80, 80, 80))
                    dpg.add_text("", tag="lbl_dataset", color=(60, 60, 60))
                    
                # ──── RIGHT PANEL: Graphs + Log ────
                with dpg.child_window(width=-1, height=-1, border=False):
                    
                    # ── Tab Bar para organizar gráficos e log ──
                    with dpg.tab_bar():
                        
                        # TAB 1: Loss Graphs
                        with dpg.tab(label="Loss"):
                            with dpg.plot(label="Training Loss", height=280, width=-1, tag="plot_loss"):
                                dpg.add_plot_legend()
                                x_axis = dpg.add_plot_axis(dpg.mvXAxis, label="Epoch", tag="loss_x")
                                with dpg.plot_axis(dpg.mvYAxis, label="Loss", tag="loss_y"):
                                    dpg.add_line_series([], [], label="Box Loss", tag="series_box",
                                                       parent="loss_y")
                                    dpg.add_line_series([], [], label="Cls Loss", tag="series_cls",
                                                       parent="loss_y")
                                    dpg.add_line_series([], [], label="DFL Loss", tag="series_dfl",
                                                       parent="loss_y")
                                    
                                # Cor das séries
                                with dpg.theme() as t_box:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (255, 80, 80), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_box", t_box)
                                
                                with dpg.theme() as t_cls:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (80, 160, 255), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_cls", t_cls)
                                
                                with dpg.theme() as t_dfl:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (80, 255, 160), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_dfl", t_dfl)
                        
                        # TAB 2: mAP Graphs
                        with dpg.tab(label="mAP"):
                            with dpg.plot(label="Validation mAP", height=280, width=-1, tag="plot_map"):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="Epoch", tag="map_x")
                                with dpg.plot_axis(dpg.mvYAxis, label="mAP", tag="map_y"):
                                    dpg.add_line_series([], [], label="mAP50", tag="series_map50",
                                                       parent="map_y")
                                    dpg.add_line_series([], [], label="mAP50-95", tag="series_map95",
                                                       parent="map_y")
                                    dpg.add_line_series([], [], label="Precision", tag="series_prec",
                                                       parent="map_y")
                                    dpg.add_line_series([], [], label="Recall", tag="series_rec",
                                                       parent="map_y")
                                
                                with dpg.theme() as t_m50:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (255, 180, 0), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_map50", t_m50)
                                
                                with dpg.theme() as t_m95:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (0, 255, 180), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_map95", t_m95)
                                
                                with dpg.theme() as t_prec:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (255, 220, 80), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_prec", t_prec)
                                
                                with dpg.theme() as t_rec:
                                    with dpg.theme_component(dpg.mvLineSeries):
                                        dpg.add_theme_color(dpg.mvPlotCol_Line, (200, 80, 255), category=dpg.mvThemeCat_Plots)
                                dpg.bind_item_theme("series_rec", t_rec)
                        
                        # TAB 3: Raw Log
                        with dpg.tab(label="Log"):
                            dpg.add_input_text(
                                tag="train_log", multiline=True, readonly=True,
                                width=-1, height=280, default_value=""
                            )

    def _build_theme(self):
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (15, 15, 20))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (20, 20, 28))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (30, 30, 40))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (40, 40, 55))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 60, 85))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (255, 140, 0))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (25, 25, 35))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (35, 35, 50))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (255, 140, 0))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (255, 180, 50))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (50, 50, 70))
                dpg.add_theme_color(dpg.mvThemeCol_Tab, (30, 30, 42))
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (50, 50, 70))
                dpg.add_theme_color(dpg.mvThemeCol_TabActive, (60, 60, 85))
                dpg.add_theme_color(dpg.mvThemeCol_Separator, (40, 40, 55))
                dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, (40, 40, 55))
                dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, (30, 30, 42))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (210, 210, 210))

                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)

            # ── Cores do Plot (mvPlotCol_* dentro de mvPlot component) ──
            with dpg.theme_component(dpg.mvPlot):
                dpg.add_theme_color(dpg.mvPlotCol_FrameBg, (12, 12, 18), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_PlotBg, (12, 12, 18), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_PlotBorder, (40, 40, 55), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_LegendBg, (20, 20, 28), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_LegendBorder, (40, 40, 55), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_LegendText, (200, 200, 200), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_AxisText, (140, 140, 140), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_color(dpg.mvPlotCol_AxisGrid, (35, 35, 50), category=dpg.mvThemeCat_Plots)

        dpg.bind_theme(theme)
    
    # ════════════════════════════════════════════
    #  TRAINING CONTROL
    # ════════════════════════════════════════════
    
    def start_training(self):
        if self._training_active:
            return
        
        # Reset graph data
        self._epochs.clear()
        self._box_loss.clear()
        self._cls_loss.clear()
        self._dfl_loss.clear()
        self._map50.clear()
        self._map50_95.clear()
        self._precision.clear()
        self._recall.clear()
        self._current_epoch = 0
        
        model = dpg.get_value("yolo_model")
        epochs = dpg.get_value("yolo_epochs")
        imgsz = dpg.get_value("yolo_imgsz")
        batch = dpg.get_value("yolo_batch")
        name = dpg.get_value("yolo_name")
        self._total_epochs = epochs
        self._start_time = time.time()
        
        do_autolabel = dpg.get_value("chk_autolabel")
        confidence   = dpg.get_value("label_conf")
        
        self._training_active = True
        dpg.configure_item("btn_train", enabled=False)
        dpg.configure_item("btn_stop", enabled=True)
        dpg.configure_item("lbl_state", default_value="LABELING...", color=(255, 180, 0))
        dpg.configure_item("lbl_dataset", default_value=f"Dataset: {DATASET_YAML}")
        dpg.set_value("train_log", "")
        dpg.set_value("progress_bar", 0.0)
        
        t = threading.Thread(target=self._run_training, 
                           args=(model, epochs, imgsz, batch, name, do_autolabel, confidence), daemon=True)
        t.start()
    
    def _update_inbox_count(self):
        """Atualiza contador de imagens na inbox."""
        try:
            ensure_dirs()
            n = len(get_inbox_images())
            color = (100, 255, 100) if n > 0 else (100, 100, 100)
            dpg.configure_item("lbl_inbox_count", 
                              default_value=f"  {n} imagem(ns) na inbox",
                              color=color)
        except Exception:
            pass
    
    def stop_training(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._append_log("\n[!] TREINAMENTO INTERROMPIDO PELO USUARIO\n")
            dpg.configure_item("lbl_state", default_value="STOPPED", color=(255, 255, 0))
    
    def _run_auto_label(self, confidence: float):
        """Roda o auto-labeler na inbox antes de treinar."""
        ensure_dirs()
        inbox = get_inbox_images()
        
        if not inbox:
            self._append_log("[Auto-Label] Inbox vazia — nenhuma imagem nova.\n")
            return
        
        self._append_log(f"[Auto-Label] {len(inbox)} imagens na inbox. Anotando...\n")
        dpg.configure_item("lbl_state", default_value="LABELING...", color=(255, 180, 0))
        
        try:
            # Redirecionar print do process_inbox para o log
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                labeled = process_inbox(confidence=confidence, dry_run=False)
            output = buf.getvalue()
            for line in output.splitlines():
                self._append_log(line + "\n")
            
            self._append_log(f"[Auto-Label] Concluido: {labeled} imagens anotadas.\n")
            self._append_log("─" * 60 + "\n")
        except Exception as e:
            self._append_log(f"[Auto-Label] ERRO: {e}\n")

    def _run_training(self, model, epochs, imgsz, batch, name, do_autolabel: bool = True, confidence: float = 0.40):
        # ── Passo 1: Auto-Label da inbox ──
        if do_autolabel:
            self._run_auto_label(confidence)
        
        dpg.configure_item("lbl_state", default_value="TRAINING", color=(100, 255, 100))
        self._start_time = time.time()  # Resetar timer após labeling
        
        cmd = [
            "yolo", "detect", "train",
            f"model={model}",
            f"data={DATASET_YAML}",
            f"epochs={epochs}",
            f"imgsz={imgsz}",
            f"batch={batch}",
            f"name={name}",
            f"project={RUNS_DIR}",
            "exist_ok=True"
        ]
        
        self._append_log(f"$ {' '.join(cmd)}\n{'─'*60}\n")
        
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=BASE_DIR,
                encoding='utf-8', errors='replace'
            )
            
            for line in self._process.stdout:
                self._append_log(line)
                self._parse_metrics(line)
            
            self._process.wait()
            
            if self._process.returncode == 0:
                best_path = os.path.join(RUNS_DIR, name, "weights", "best.pt")
                dpg.configure_item("lbl_state", 
                                  default_value="COMPLETED", color=(100, 255, 100))
                elapsed = time.time() - self._start_time
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                dpg.configure_item("lbl_time", 
                                  default_value=f"Tempo total: {mins}m {secs}s")
                
                # ── Exportar best.pt para o orbwalker automaticamente ──
                export_msg = ""
                if os.path.exists(best_path) and ORBWALKER_MODELS_DIR:
                    try:
                        os.makedirs(ORBWALKER_MODELS_DIR, exist_ok=True)
                        dest = os.path.join(ORBWALKER_MODELS_DIR, "best.pt")
                        shutil.copy2(best_path, dest)
                        export_msg = f"  best.pt exportado → {dest}\n"
                    except Exception as ex:
                        export_msg = f"  [!] Falha ao exportar best.pt: {ex}\n"
                
                self._append_log(
                    f"\n{'═'*60}\n"
                    f"  TREINAMENTO CONCLUIDO!\n"
                    f"  best.pt → {best_path}\n"
                    f"{export_msg}"
                    f"  Tempo: {mins}m {secs}s\n"
                    f"{'═'*60}\n"
                )
                dpg.set_value("progress_bar", 1.0)
            else:
                dpg.configure_item("lbl_state", 
                                  default_value="ERROR", color=(255, 100, 100))
                self._append_log(f"\n[X] Processo retornou codigo {self._process.returncode}\n")
                
        except FileNotFoundError:
            dpg.configure_item("lbl_state", 
                              default_value="ERROR", color=(255, 100, 100))
            self._append_log(
                "[X] Comando 'yolo' nao encontrado.\n"
                "    Instale com: pip install ultralytics\n"
            )
        except Exception as e:
            dpg.configure_item("lbl_state", 
                              default_value="ERROR", color=(255, 100, 100))
            self._append_log(f"[X] ERRO: {e}\n")
        finally:
            self._training_active = False
            self._process = None
            dpg.configure_item("btn_train", enabled=True)
            dpg.configure_item("btn_stop", enabled=False)

    # ════════════════════════════════════════════
    #  METRICS PARSING & GRAPH UPDATES
    # ════════════════════════════════════════════

    def _parse_metrics(self, line):
        """Parseia uma linha de output do YOLO e atualiza gráficos."""
        
        # ── Training line (loss) ──
        match = TRAIN_LINE_RE.search(line)
        if match:
            epoch = int(match.group(1))
            total = int(match.group(2))
            box_l = float(match.group(3))
            cls_l = float(match.group(4))
            dfl_l = float(match.group(5))
            
            self._current_epoch = epoch
            self._total_epochs = total
            
            # Só adicionar se é uma nova época
            if not self._epochs or self._epochs[-1] != epoch:
                self._epochs.append(epoch)
                self._box_loss.append(box_l)
                self._cls_loss.append(cls_l)
                self._dfl_loss.append(dfl_l)
            else:
                # Atualizar a última (pode ter múltiplas linhas por epoch)
                self._box_loss[-1] = box_l
                self._cls_loss[-1] = cls_l
                self._dfl_loss[-1] = dfl_l
            
            # Atualizar UI
            self._update_loss_graph()
            self._update_values(box_l, cls_l, dfl_l)
            self._update_progress(epoch, total)
            return
        
        # ── Validation metrics line ──
        match = VAL_METRICS_RE.search(line)
        if match:
            prec = float(match.group(1))
            rec = float(match.group(2))
            m50 = float(match.group(3))
            m95 = float(match.group(4))
            
            # Adicionar ao epoch atual
            epoch = self._current_epoch
            if not self._map50 or len(self._map50) < len(self._epochs):
                self._map50.append(m50)
                self._map50_95.append(m95)
                self._precision.append(prec)
                self._recall.append(rec)
            else:
                self._map50[-1] = m50
                self._map50_95[-1] = m95
                self._precision[-1] = prec
                self._recall[-1] = rec
            
            self._update_map_graph()
            self._update_val_values(prec, rec, m50, m95)

    def _update_loss_graph(self):
        try:
            epochs_f = [float(e) for e in self._epochs]
            dpg.set_value("series_box", [epochs_f, self._box_loss])
            dpg.set_value("series_cls", [epochs_f, self._cls_loss])
            dpg.set_value("series_dfl", [epochs_f, self._dfl_loss])
            dpg.fit_axis_data("loss_x")
            dpg.fit_axis_data("loss_y")
        except Exception:
            pass
    
    def _update_map_graph(self):
        try:
            # mAP epochs podem ter menos pontos que loss
            ep = [float(e) for e in self._epochs[:len(self._map50)]]
            dpg.set_value("series_map50", [ep, self._map50])
            dpg.set_value("series_map95", [ep, self._map50_95])
            dpg.set_value("series_prec", [ep, self._precision])
            dpg.set_value("series_rec", [ep, self._recall])
            dpg.fit_axis_data("map_x")
            dpg.fit_axis_data("map_y")
        except Exception:
            pass
    
    def _update_values(self, box, cls, dfl):
        try:
            dpg.configure_item("val_box", default_value=f"{box:.4f}", 
                              color=(255, 100, 100) if box > 1.0 else (100, 255, 100))
            dpg.configure_item("val_cls", default_value=f"{cls:.4f}",
                              color=(100, 180, 255) if cls > 1.0 else (100, 255, 100))
            dpg.configure_item("val_dfl", default_value=f"{dfl:.4f}",
                              color=(100, 255, 180) if dfl > 1.0 else (100, 255, 100))
        except Exception:
            pass
    
    def _update_val_values(self, prec, rec, m50, m95):
        try:
            dpg.configure_item("val_prec", default_value=f"{prec:.4f}",
                              color=(100, 255, 100) if prec > 0.5 else (255, 200, 100))
            dpg.configure_item("val_rec", default_value=f"{rec:.4f}",
                              color=(100, 255, 100) if rec > 0.5 else (255, 200, 100))
            dpg.configure_item("val_map50", default_value=f"{m50:.4f}",
                              color=(100, 255, 100) if m50 > 0.5 else (255, 180, 0))
            dpg.configure_item("val_map95", default_value=f"{m95:.4f}",
                              color=(100, 255, 100) if m95 > 0.3 else (255, 180, 0))
        except Exception:
            pass
    
    def _update_progress(self, epoch, total):
        try:
            progress = epoch / max(total, 1)
            dpg.set_value("progress_bar", progress)
            dpg.configure_item("lbl_progress", 
                              default_value=f"  Epoch {epoch}/{total}")
            
            # ETA
            if self._start_time and epoch > 0:
                elapsed = time.time() - self._start_time
                per_epoch = elapsed / epoch
                remaining = per_epoch * (total - epoch)
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                dpg.configure_item("lbl_eta", 
                                  default_value=f"  |  ETA: {mins}m {secs}s")
                
                elapsed_m = int(elapsed // 60)
                elapsed_s = int(elapsed % 60)
                dpg.configure_item("lbl_time",
                                  default_value=f"Elapsed: {elapsed_m}m {elapsed_s}s")
        except Exception:
            pass

    def _append_log(self, text):
        try:
            current = dpg.get_value("train_log")
            lines = (current + text).split("\n")
            if len(lines) > 500:
                lines = lines[-500:]
            dpg.set_value("train_log", "\n".join(lines))
        except Exception:
            pass


if __name__ == "__main__":
    print("\n ╔══════════════════════════════════════════╗")
    print(" ║   YOLO NEURAL TRAINER PRO — GUI          ║")
    print(" ║   Orbwalker Vision Training Suite         ║")
    print(" ╚══════════════════════════════════════════╝\n")
    ensure_dirs()
    app = TrainerUI()
    app._update_inbox_count()
