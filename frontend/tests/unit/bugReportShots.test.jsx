// Screenshots on the report page (owner, 2026-10-05): attach one, see it, send it with the
// report; and be told up front when this build's tracker cannot carry it.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import BugReport from "../../src/pages/BugReport";
import { api } from "../../src/lib/api";

const png = () => new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0, 0])], "shot.png",
  { type: "image/png" });

function page(sink, attachments) {
  vi.spyOn(api, "reportContext").mockResolvedValue({ app: {}, sink, attachments });
  return render(<MemoryRouter><BugReport /></MemoryRouter>);
}

afterEach(() => vi.restoreAllMocks());

describe("BugReport screenshots", () => {
  it("attaches a picked image and sends it with the report", async () => {
    const send = vi.spyOn(api, "reportBug").mockResolvedValue({ ok: true, configured: true,
      sink: "relay", key: "SCRUM-9", attached: 1 });
    page("relay", true);
    await userEvent.upload(screen.getByTestId("shot-input"), png());
    expect(await screen.findByAltText("shot.png")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/What you did/), "it broke");
    await userEvent.click(screen.getByRole("button", { name: /send report/i }));
    await waitFor(() => expect(send).toHaveBeenCalled());
    const body = send.mock.calls[0][0];
    expect(body.attachments).toHaveLength(1);
    expect(body.attachments[0]).toMatchObject({ name: "shot.png", type: "image/png" });
    expect(body.attachments[0].data).toMatch(/^iVBORw0KGgo/);    // base64 of the PNG magic
    expect(await screen.findByText(/1 screenshot is attached/)).toBeInTheDocument();
  });

  it("refuses a file that is not an image", async () => {
    page("relay", true);
    const doc = new File(["hello"], "notes.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByTestId("shot-input"), doc, { applyAccept: false });
    expect(await screen.findByText(/not a PNG, JPEG, WebP or GIF/)).toBeInTheDocument();
  });

  it("says before sending that a text-only tracker will not carry the screenshot", async () => {
    page("webhook", false);
    await userEvent.upload(screen.getByTestId("shot-input"), png());
    expect(await screen.findByText(/takes text only/)).toBeInTheDocument();
  });
});
