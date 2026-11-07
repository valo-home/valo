import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const csp = {
	mode: 'auto',
	directives: {
		'default-src': ['self'],
		'script-src': ['self'],
		'style-src': ['self', 'unsafe-inline'],
		'img-src': ['self', 'data:', 'blob:'],
		'media-src': ['self', 'blob:'],
		'font-src': ['self', 'data:'],
		'connect-src': ['self', 'ws:', 'wss:'],
		'frame-src': ['self'],
		'frame-ancestors': ['self'],
		'form-action': ['self'],
		'base-uri': ['self'],
		'object-src': ['none']
	}
};

export default defineConfig({
	plugins: [sveltekit({ adapter: adapter(), csp })]
});
