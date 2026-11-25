declare module 'smiles-drawer' {
  type DrawerOptions = { width?: number; height?: number; [key: string]: unknown };

  class SvgDrawer {
    constructor(options?: DrawerOptions);
    draw(tree: unknown, target: string | SVGSVGElement, theme?: string): void;
  }

  class Drawer {
    constructor(options?: DrawerOptions);
    draw(tree: unknown, target: string | HTMLCanvasElement, theme?: string, infoOnly?: boolean): void;
  }

  function parse(
    smiles: string,
    onSuccess: (tree: unknown) => void,
    onError?: (error: unknown) => void
  ): void;

  const SmilesDrawer: {
    SvgDrawer: typeof SvgDrawer;
    Drawer: typeof Drawer;
    parse: typeof parse;
  };

  export default SmilesDrawer;
}
