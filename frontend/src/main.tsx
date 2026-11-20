import ReactDOM from 'react-dom/client';
import { App } from './App';

// StrictMode double-mounts effects and breaks Deepscatter (global canvas IDs / WebGL).
ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
