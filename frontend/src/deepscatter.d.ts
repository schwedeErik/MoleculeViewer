/** Ambient types for deepscatter (default export is Scatterplot). */
declare module 'deepscatter' {
  export type PlotAPIPrefs = {
    source_url?: string;
    max_points?: number;
    alpha?: number;
    zoom_balance?: number;
    point_size?: number;
    background_color?: string;
    duration?: number;
    zoom?: { bbox?: { x: [number, number]; y: [number, number] } };
    encoding?: Record<string, unknown>;
    click_function?: ((datum: Record<string, unknown>) => void) | string;
    [key: string]: unknown;
  };

  export default class Scatterplot {
    constructor(
      selector: string | HTMLElement,
      width?: number,
      height?: number,
      options?: Record<string, unknown>
    );
    plotAPI(prefs: PlotAPIPrefs): Promise<unknown>;
    destroy(): void;
    click_function: ((datum: Record<string, unknown>) => void) | string;
    /** HTML of deepscatter's built-in tooltip for the point under the cursor. */
    tooltip_html: ((datum: Record<string, unknown>) => string) | string;
    /** Called on mouse move with the point under the cursor, or [] if there is none. */
    highlit_point_change: ((points: Record<string, unknown>[]) => void) | string;
    on_zoom?: (transform: unknown) => void;
  }
}
