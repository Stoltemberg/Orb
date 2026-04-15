"""
screen_capture.py — Captura de tela de alta performance.
DXCam com fallback para mss. Suporte a ultrawide.
"""
import numpy as np
import logging
import time

logger = logging.getLogger("ExternalOrbwalker.ScreenCapture")

try:
    import dxcam
    HAS_DXCAM = True
except ImportError:
    HAS_DXCAM = False


class ScreenCapture:
    """
    Captura frames da tela. DXCam (GPU) quando disponível, mss como fallback.
    Modo NON-BLOCKING: usa get_latest_frame() que retorna None se não há frame novo.
    """

    def __init__(self, target_fps: int = 60, region: tuple = None):
        self.target_fps = target_fps
        self.region = region
        self._camera = None
        self._use_dxcam = HAS_DXCAM
        self._started = False

    def start(self):
        """Inicializa o DXCam ou prepara mss."""
        if self._use_dxcam:
            try:
                # DXCam: device_idx e output_idx são opcionais
                self._camera = dxcam.create(output_color="BGR")

                # Tentar iniciar — NÃO passar region se for None
                if self.region:
                    self._camera.start(target_fps=self.target_fps, region=self.region)
                else:
                    self._camera.start(target_fps=self.target_fps)

                # Esperar primeiro frame (DXCam precisa "aquecer")
                for _ in range(30):
                    test = self._camera.get_latest_frame()
                    if test is not None:
                        h, w = test.shape[:2]
                        logger.info(f"DXCam OK @ {w}x{h}, target {self.target_fps} FPS")
                        self._started = True
                        return
                    time.sleep(0.1)

                logger.warning("DXCam: nenhum frame após 3s warmup")
                self._use_dxcam = False
            except Exception as e:
                logger.warning(f"DXCam falhou: {e}. Usando mss.")
                self._use_dxcam = False
                self._camera = None

        if not self._use_dxcam:
            logger.info("Usando mss para captura (mais lento, ~30-60 FPS)")
            self._started = True

    def stop(self):
        """Para o DXCam."""
        if self._camera:
            try:
                self._camera.stop()
            except Exception:
                pass
            # DXCam precisa ser deletado para liberar recursos
            try:
                del self._camera
            except Exception:
                pass
            self._camera = None
        self._started = False
        logger.info("Screen capture stopped")

    def grab(self) -> np.ndarray | None:
        """Captura um frame. Retorna None se não disponível."""
        if self._use_dxcam and self._camera:
            try:
                return self._camera.get_latest_frame()
            except Exception:
                return None
        else:
            return self._grab_mss()

    def _grab_mss(self) -> np.ndarray | None:
        """Captura via mss (fallback)."""
        try:
            import mss
            with mss.mss() as sct:
                if self.region:
                    monitor = {
                        "left": self.region[0],
                        "top": self.region[1],
                        "width": self.region[2] - self.region[0],
                        "height": self.region[3] - self.region[1],
                    }
                else:
                    monitor = sct.monitors[1]

                img = sct.grab(monitor)
                frame = np.array(img)
                return frame[:, :, :3]  # BGRA → BGR
        except Exception:
            return None

    def get_screen_size(self) -> tuple:
        """Retorna (width, height) da tela."""
        import ctypes
        user32 = ctypes.windll.user32
        # Em ultrawide, GetSystemMetrics(0) retorna a largura total
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
