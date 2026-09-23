<?php
/**
 * Plugin Name: Post Bot REST metadata
 * Description: Exposes the SEO and Elementor metadata needed by Blog Post Bot over REST.
 */

add_action('init', static function (): void {
    $keys = [
        '_yoast_wpseo_title',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_focuskw',
        '_elementor_edit_mode',
    ];

    foreach (['post', 'page'] as $post_type) {
        foreach ($keys as $key) {
            register_post_meta($post_type, $key, [
                'type'              => 'string',
                'single'            => true,
                'show_in_rest'      => true,
                'auth_callback'     => static function ($allowed, $meta_key, $post_id, $user_id): bool {
                    return user_can($user_id, 'edit_post', $post_id);
                },
                'sanitize_callback' => 'sanitize_text_field',
            ]);
        }
    }
});
