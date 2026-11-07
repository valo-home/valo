import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	BACKEND_URL: { description: 'Valo backend base URL', schema: (v) => v || 'http://localhost:8000' }
});
