import { BrowserRouter } from "react-router-dom";
import RoutesView from "./routes";

export default function App() {
  return (
    <BrowserRouter>
      <RoutesView />
    </BrowserRouter>
  );
}
