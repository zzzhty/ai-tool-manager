import { defineConfig } from 'vitest/config';
export default defineConfig({ clearScreen: false, build: { target: 'es2022' }, test: { environment: 'happy-dom' } });
