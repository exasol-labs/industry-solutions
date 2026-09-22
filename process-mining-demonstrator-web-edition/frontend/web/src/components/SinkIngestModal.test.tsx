import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'

vi.mock('../api', () => ({
  api: {
    sinkIngestInfo: vi.fn(async () => ({
      method: 'POST', path: '/ingest', httpPort: 8129, httpsPort: 8492, tlsMode: 'off',
      activeScheme: 'http', activeContainerPort: 8129,
      consoleHttpPort: 8100, consoleHttpsPort: 8463, titleShort: 'AGENTLOG',
      endpointUrl: '',
    })),
    setSinkEndpoint: vi.fn(async (_id: string, url: string) => ({ endpointUrl: url })),
  },
}))

import { api } from '../api'
import { SinkIngestModal } from './SinkIngestModal'
import { renderSettled } from '../test/renderSettled'

afterEach(() => vi.clearAllMocks())

describe('SinkIngestModal', () => {
  // The read-only <textarea> holds the active tab's code; the URL/token <input>s are editable.
  const codeText = () =>
    (screen.getAllByRole('textbox') as HTMLTextAreaElement[]).find((el) => el.readOnly)?.value ?? ''
  const clickTab = (name: string) =>
    fireEvent.click(screen.getByRole('button', { name }))

  it('computes the endpoint URL, embeds the token, and offers all example tabs', async () => {
    await renderSettled(
      <SinkIngestModal sourceId="s1" token="tok-abc" name="Agent sink" onClose={() => {}} />,
    )
    // The URL field is pre-filled with the auto-detected URL (no offset in jsdom).
    expect(await screen.findByDisplayValue('http://localhost:8129/ingest')).toBeTruthy()
    // The token field is pre-filled from the just-minted token.
    expect(screen.getByDisplayValue('tok-abc')).toBeTruthy()
    // Every language tab is present, and the tabs are sorted alphabetically by label.
    const labels = ['AI Agents (SKILL.md)', 'C#', 'CLI (curl)', 'Go', 'JavaScript', 'Mojo', 'Python', 'Rust', 'TypeScript']
    for (const label of labels) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy()
    }
    const order = screen
      .getAllByRole('button')
      .map((b) => b.textContent ?? '')
      .filter((t) => labels.includes(t))
    expect(order).toEqual(labels)
    // The default (Python) example embeds the token, and the download targets that file.
    expect(codeText()).toContain('requests.post')
    expect(codeText()).toContain('TOKEN = "tok-abc"')
    expect(screen.getByRole('button', { name: /Download send_events\.py/ })).toBeTruthy()
    // Switching to CLI shows the curl with the token; the download becomes the shell script.
    clickTab('CLI (curl)')
    expect(codeText()).toContain('Authorization: Bearer tok-abc')
    expect(screen.getByRole('button', { name: /Download send_events\.sh/ })).toBeTruthy()
    // The AI-agent SKILL.md is one of the tabs and downloads as SKILL.md.
    clickTab('AI Agents (SKILL.md)')
    // The SKILL.md leads with YAML frontmatter so an agent runtime can register it.
    expect(codeText()).toMatch(/^---\nname: AI-Agent-Logger\ndescription: .+\n---/)
    expect(codeText()).toContain('# Skill: Emit process-mining journey events')
    expect(screen.getByRole('button', { name: /Download SKILL\.md/ })).toBeTruthy()
  })

  it('uses a placeholder token when opened without one', async () => {
    await renderSettled(<SinkIngestModal sourceId="s1" name="Agent sink" onClose={() => {}} />)
    await screen.findByDisplayValue('http://localhost:8129/ingest')
    expect(codeText()).toContain('TOKEN = "<YOUR_TOKEN>"') // Python default tab
    clickTab('CLI (curl)')
    expect(codeText()).toContain('Bearer <YOUR_TOKEN>')
  })

  it('pre-fills a saved endpoint-URL override', async () => {
    ;(api.sinkIngestInfo as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      method: 'POST', path: '/ingest', httpPort: 8129, httpsPort: 8492, tlsMode: 'required',
      activeScheme: 'https', activeContainerPort: 8492,
      consoleHttpPort: 8100, consoleHttpsPort: 8463, titleShort: 'AGENTLOG',
      endpointUrl: 'https://pm.example.com/ingest',
    })
    await renderSettled(<SinkIngestModal sourceId="s1" token="tok-abc" onClose={() => {}} />)
    expect(await screen.findByDisplayValue('https://pm.example.com/ingest')).toBeTruthy()
    expect(codeText()).toContain('https://pm.example.com/ingest') // Python default tab
  })

  it('lets the user override the URL and paste a token — both flow into the examples', async () => {
    await renderSettled(<SinkIngestModal sourceId="s1" onClose={() => {}} />)
    const urlInput = await screen.findByDisplayValue('http://localhost:8129/ingest')
    fireEvent.change(urlInput, { target: { value: 'https://pm.example.com/ingest' } })
    fireEvent.change(screen.getByPlaceholderText('<YOUR_TOKEN>'), { target: { value: 'pasted-tok' } })
    clickTab('CLI (curl)')
    await waitFor(() => {
      const c = codeText()
      expect(c).toContain('https://pm.example.com/ingest')
      expect(c).toContain('Authorization: Bearer pasted-tok')
      expect(c).toContain('-k') // https → self-signed flag
    })
  })

  it('persists the URL override via setSinkEndpoint on Save', async () => {
    await renderSettled(<SinkIngestModal sourceId="s1" token="tok-abc" onClose={() => {}} />)
    const urlInput = await screen.findByDisplayValue('http://localhost:8129/ingest')
    fireEvent.change(urlInput, { target: { value: 'https://pm.example.com/ingest' } })
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    await waitFor(() =>
      expect(api.setSinkEndpoint).toHaveBeenCalledWith('s1', 'https://pm.example.com/ingest'),
    )
  })
})
