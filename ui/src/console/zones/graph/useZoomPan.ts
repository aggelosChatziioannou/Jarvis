import { useState, useCallback, useRef, useEffect } from 'react';
import type { RefObject } from 'react';

const MIN_ZOOM = 0.3;
const MAX_ZOOM = 2.0;
const ZOOM_STEP = 0.1;
const WHEEL_SENSITIVITY = 0.001;
const DEFAULT_ZOOM = 0.8; // 80% — perfect view of the whole map

export function useZoomPan(containerRef: RefObject<HTMLElement | null>) {
  const [zoom, setZoomState] = useState(DEFAULT_ZOOM);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isPanning, setIsPanning] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const zoomRef = useRef(zoom); zoomRef.current = zoom;
  const panXRef = useRef(panX); panXRef.current = panX;
  const panYRef = useRef(panY); panYRef.current = panY;

  // Initialize pan to viewport center (so YOU node at 0,0 is centered)
  useEffect(() => {
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      setPanX(rect.width / 2);
      setPanY(rect.height / 2);
    }
  }, [containerRef]);

  const setZoom = useCallback((newZoom: number) => {
    setZoomState(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoom)));
  }, []);

  const zoomIn = useCallback(() => setZoomState((prev) => Math.min(MAX_ZOOM, prev + ZOOM_STEP)), []);
  const zoomOut = useCallback(() => setZoomState((prev) => Math.max(MIN_ZOOM, prev - ZOOM_STEP)), []);

  const resetView = useCallback(() => {
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      setPanX(rect.width / 2);
      setPanY(rect.height / 2);
    }
    setZoomState(DEFAULT_ZOOM);
  }, [containerRef]);

  // Wheel zoom is handled via a NATIVE non-passive listener below. React's synthetic
  // onWheel is registered passively, so calling preventDefault() there is ignored and
  // logs "Unable to preventDefault inside passive event listener". handleWheel is kept
  // as a no-op for API compatibility with consumers that still spread onWheel.
  const handleWheel = useCallback(() => {}, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const centerX = rect.width / 2;
      const centerY = rect.height / 2;
      const z = zoomRef.current;
      // Zoom relative to viewport center so the YOU node (at 0,0) stays centered
      const graphCenterXBefore = (centerX - panXRef.current) / z;
      const graphCenterYBefore = (centerY - panYRef.current) / z;
      const delta = -e.deltaY * WHEEL_SENSITIVITY;
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z + delta));
      setZoomState(newZoom);
      setPanX(centerX - graphCenterXBefore * newZoom);
      setPanY(centerY - graphCenterYBefore * newZoom);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [containerRef]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      if ((e.target as HTMLElement).closest('[data-node]')) return;
      setIsPanning(true);
      dragStart.current = { x: e.clientX, y: e.clientY, panX, panY };
    },
    [panX, panY]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isPanning) return;
      setPanX(dragStart.current.panX + (e.clientX - dragStart.current.x));
      setPanY(dragStart.current.panY + (e.clientY - dragStart.current.y));
    },
    [isPanning]
  );

  const handleMouseUp = useCallback(() => setIsPanning(false), []);
  const handleMouseLeave = useCallback(() => setIsPanning(false), []);
  const handleDoubleClick = useCallback(() => resetView(), [resetView]);

  return {
    zoom,
    panX,
    panY,
    isPanning,
    handleWheel,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
    handleMouseLeave,
    handleDoubleClick,
    setZoom,
    zoomIn,
    zoomOut,
    resetView,
  };
}
