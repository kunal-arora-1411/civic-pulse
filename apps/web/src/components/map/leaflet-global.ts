import L from "leaflet";

/*
 * leaflet.markercluster is a classic plugin: it extends the global `L`
 * when it's evaluated. Importing this module first (module evaluation
 * follows import order) puts Leaflet on window before the plugin runs.
 */
(window as unknown as { L: typeof L }).L = L;

export default L;
