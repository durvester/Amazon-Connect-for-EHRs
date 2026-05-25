import { render, screen } from "@testing-library/react";
import App from "../src/App";

describe("App", () => {
  it("renders the bootstrap heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Practice Fusion Voice"
    );
  });
});
