import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { createCampaign, getCampaign, updateCampaign } from "../../api/xyn";
import type { CampaignDetail } from "../../api/types";

type DrawPoint = { x: number; y: number };
type PixelRect = { left: number; top: number; width: number; height: number };
type BBox = { min_lng: number; min_lat: number; max_lng: number; max_lat: number };

const MAP_WIDTH = 760;
const MAP_HEIGHT = 440;
const STL_BOUNDS = {
  min_lng: -90.33,
  max_lng: -90.17,
  min_lat: 38.54,
  max_lat: 38.73,
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function toPixelRect(a: DrawPoint, b: DrawPoint): PixelRect {
  const left = Math.min(a.x, b.x);
  const top = Math.min(a.y, b.y);
  const width = Math.abs(a.x - b.x);
  const height = Math.abs(a.y - b.y);
  return { left, top, width, height };
}

function pixelToLng(x: number): number {
  return STL_BOUNDS.min_lng + (clamp(x, 0, MAP_WIDTH) / MAP_WIDTH) * (STL_BOUNDS.max_lng - STL_BOUNDS.min_lng);
}

function pixelToLat(y: number): number {
  return STL_BOUNDS.max_lat - (clamp(y, 0, MAP_HEIGHT) / MAP_HEIGHT) * (STL_BOUNDS.max_lat - STL_BOUNDS.min_lat);
}

function rectToBBox(rect: PixelRect): BBox {
  const minLng = pixelToLng(rect.left);
  const maxLng = pixelToLng(rect.left + rect.width);
  const maxLat = pixelToLat(rect.top);
  const minLat = pixelToLat(rect.top + rect.height);
  return {
    min_lng: Number(Math.min(minLng, maxLng).toFixed(7)),
    max_lng: Number(Math.max(minLng, maxLng).toFixed(7)),
    min_lat: Number(Math.min(minLat, maxLat).toFixed(7)),
    max_lat: Number(Math.max(minLat, maxLat).toFixed(7)),
  };
}

function bboxToRect(bbox: BBox): PixelRect {
  const lngSpan = STL_BOUNDS.max_lng - STL_BOUNDS.min_lng;
  const latSpan = STL_BOUNDS.max_lat - STL_BOUNDS.min_lat;
  const left = ((bbox.min_lng - STL_BOUNDS.min_lng) / lngSpan) * MAP_WIDTH;
  const right = ((bbox.max_lng - STL_BOUNDS.min_lng) / lngSpan) * MAP_WIDTH;
  const top = ((STL_BOUNDS.max_lat - bbox.max_lat) / latSpan) * MAP_HEIGHT;
  const bottom = ((STL_BOUNDS.max_lat - bbox.min_lat) / latSpan) * MAP_HEIGHT;
  return {
    left: clamp(left, 0, MAP_WIDTH),
    top: clamp(top, 0, MAP_HEIGHT),
    width: clamp(right - left, 0, MAP_WIDTH),
    height: clamp(bottom - top, 0, MAP_HEIGHT),
  };
}

function extractBBoxFromCampaign(campaign: CampaignDetail | null): BBox | null {
  if (!campaign || typeof campaign.metadata !== "object" || campaign.metadata === null) return null;
  const metadata = campaign.metadata as Record<string, unknown>;
  const raw = metadata.monitoring_bounds;
  if (!raw || typeof raw !== "object") return null;
  const bounds = raw as Record<string, unknown>;
  const minLng = Number(bounds.min_lng);
  const minLat = Number(bounds.min_lat);
  const maxLng = Number(bounds.max_lng);
  const maxLat = Number(bounds.max_lat);
  if (![minLng, minLat, maxLng, maxLat].every(Number.isFinite)) return null;
  return { min_lng: minLng, min_lat: minLat, max_lng: maxLng, max_lat: maxLat };
}

export default function CampaignMapWorkflowPage({
  workspaceId,
  campaignId,
}: {
  workspaceId: string;
  campaignId?: string;
}) {
  const navigate = useNavigate();
  const mapRef = useRef<HTMLDivElement | null>(null);
  const [campaignName, setCampaignName] = useState("");
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(Boolean(campaignId));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragStart, setDragStart] = useState<DrawPoint | null>(null);
  const [selectionRect, setSelectionRect] = useState<PixelRect | null>(null);

  useEffect(() => {
    if (!campaignId || !workspaceId) return;
    let mounted = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const detail = await getCampaign(campaignId, workspaceId);
        if (!mounted) return;
        setCampaign(detail);
        setCampaignName(detail.name || "");
        const bbox = extractBBoxFromCampaign(detail);
        setSelectionRect(bbox ? bboxToRect(bbox) : null);
      } catch (err) {
        if (!mounted) return;
        setError((err as Error).message || "Failed to load campaign.");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [campaignId, workspaceId]);

  const selectedBBox = useMemo(() => (selectionRect ? rectToBBox(selectionRect) : null), [selectionRect]);

  const startDraw = (event: MouseEvent<HTMLDivElement>) => {
    if (!mapRef.current) return;
    const rect = mapRef.current.getBoundingClientRect();
    const x = clamp(event.clientX - rect.left, 0, MAP_WIDTH);
    const y = clamp(event.clientY - rect.top, 0, MAP_HEIGHT);
    setDragStart({ x, y });
    setSelectionRect({ left: x, top: y, width: 0, height: 0 });
  };

  const updateDraw = (event: MouseEvent<HTMLDivElement>) => {
    if (!dragStart || !mapRef.current) return;
    const rect = mapRef.current.getBoundingClientRect();
    const x = clamp(event.clientX - rect.left, 0, MAP_WIDTH);
    const y = clamp(event.clientY - rect.top, 0, MAP_HEIGHT);
    setSelectionRect(toPixelRect(dragStart, { x, y }));
  };

  const stopDraw = () => {
    setDragStart(null);
  };

  const persist = async () => {
    if (!workspaceId || !selectedBBox) return;
    if (!campaignName.trim()) {
      setError("Campaign name is required.");
      return;
    }
    try {
      setSaving(true);
      setError(null);
      const metadata = {
        ...(campaign?.metadata || {}),
        monitoring_bounds: selectedBBox,
        monitoring_mode: "rectangle_box_selection",
      };
      if (campaignId) {
        const updated = await updateCampaign(campaignId, {
          workspace_id: workspaceId,
          name: campaignName.trim(),
          metadata,
        });
        setCampaign(updated);
      } else {
        const created = await createCampaign({
          workspace_id: workspaceId,
          name: campaignName.trim(),
          description: "Campaign created from map box selection workflow.",
          metadata,
        });
        navigate(`/w/${encodeURIComponent(workspaceId)}/a/campaigns/${encodeURIComponent(created.id)}`, { replace: true });
      }
    } catch (err) {
      setError((err as Error).message || "Failed to save campaign.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card stack">
      <h2>{campaignId ? "Campaign Map Selection" : "Create Campaign"}</h2>
      <p className="muted">
        Draw a rectangle over the St. Louis City map panel to define campaign monitoring bounds, then save the campaign.
      </p>
      {loading ? <p className="muted">Loading campaign…</p> : null}
      {error ? <p className="danger">{error}</p> : null}
      <label className="stack" htmlFor="campaign-name">
        <span className="small muted">Campaign name</span>
        <input
          id="campaign-name"
          value={campaignName}
          onChange={(event) => setCampaignName(event.target.value)}
          placeholder="St. Louis North Market Watch"
        />
      </label>
      <div
        ref={mapRef}
        data-testid="campaign-map-canvas"
        role="application"
        aria-label="Campaign map selection"
        style={{
          width: `${MAP_WIDTH}px`,
          height: `${MAP_HEIGHT}px`,
          position: "relative",
          borderRadius: "12px",
          border: "1px solid rgba(74, 85, 104, 0.45)",
          background:
            "linear-gradient(160deg, rgba(12,41,84,0.75), rgba(31,80,128,0.85) 50%, rgba(23,124,176,0.75) 100%)",
          overflow: "hidden",
          userSelect: "none",
          cursor: dragStart ? "crosshair" : "cell",
        }}
        onMouseDown={startDraw}
        onMouseMove={updateDraw}
        onMouseUp={stopDraw}
        onMouseLeave={stopDraw}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "repeating-linear-gradient(0deg, rgba(255,255,255,0.05), rgba(255,255,255,0.05) 1px, transparent 1px, transparent 44px), repeating-linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.05) 1px, transparent 1px, transparent 44px)",
          }}
        />
        <div style={{ position: "absolute", top: 10, left: 10, color: "#dcecff", fontSize: "12px", fontWeight: 600 }}>St. Louis City Map Selection</div>
        {selectionRect ? (
          <div
            data-testid="campaign-map-selection-rect"
            style={{
              position: "absolute",
              left: `${selectionRect.left}px`,
              top: `${selectionRect.top}px`,
              width: `${selectionRect.width}px`,
              height: `${selectionRect.height}px`,
              border: "2px solid rgba(255, 186, 104, 0.98)",
              background: "rgba(255, 186, 104, 0.24)",
            }}
          />
        ) : null}
      </div>
      <div className="small muted">
        {selectedBBox ? (
          <span data-testid="campaign-bounds-readout">
            Bounds: lng[{selectedBBox.min_lng}, {selectedBBox.max_lng}] lat[{selectedBBox.min_lat}, {selectedBBox.max_lat}]
          </span>
        ) : (
          "No area selected yet. Click and drag on the map to draw a rectangle."
        )}
      </div>
      <div className="row">
        <button
          type="button"
          className="primary"
          disabled={saving || !selectedBBox || !campaignName.trim()}
          onClick={persist}
        >
          {campaignId ? "Save Bounds" : "Save Campaign"}
        </button>
      </div>
    </div>
  );
}
