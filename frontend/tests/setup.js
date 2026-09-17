// jest-dom matchers (toBeVisible, toHaveClass, ...) for every unit test, and Testing Library's
// cleanup after each one: without Vitest globals it would not hook itself in, and a component
// that renders into document.body (a Modal) would then leak into the next test.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
