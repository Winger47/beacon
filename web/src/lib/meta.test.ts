import { expect, test } from 'vitest';
import { appTitle } from './meta';

test('appTitle returns the product name', () => {
  expect(appTitle()).toBe('Kata');
});
