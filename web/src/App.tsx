import { appTitle } from './lib/meta';

export default function App(): JSX.Element {
  return (
    <main>
      <h1>{appTitle()}</h1>
      <p>Phase 0 shell. The real UI arrives in Phase 1.</p>
    </main>
  );
}
