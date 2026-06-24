/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { getDataURLFromFile } from "@web/core/utils/urls";
import { SlideUploadCategory } from "@website_slides/js/public/components/slide_upload_dialog/slide_upload_category";

// Allow selecting .html files in the Document file picker (core restricts it to PDF).
SlideUploadCategory.sourceSettings.document.acceptedFiles = "application/pdf,text/html,.html,.htm";
SlideUploadCategory.sourceSettings.document.selectFileLabel = _t("Choose a PDF or HTML file");

const isHtmlFile = (file) =>
    !!file && (file.type === "text/html" || /\.html?$/i.test(file.name || ""));

patch(SlideUploadCategory.prototype, {
    /**
     * Core's onChangeFileInput only accepts PDF or image files and runs pdf.js
     * page counting on PDFs. For HTML we just read the file as base64 and use the
     * default document icon as the preview image - the server detects it as an
     * 'html' slide_type and renders it in a sandboxed iframe.
     */
    async onChangeFileInput(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!isHtmlFile(file)) {
            return super.onChangeFileInput(ev);
        }
        // Read event-derived values synchronously: after the await below, the DOM
        // event has finished dispatching and ev.currentTarget becomes null.
        const preventOnchange = ev.currentTarget.dataset.preventOnchange;
        this._alertRemove();
        if (file.size > 25 * 1024 * 1024) {
            this._alertDisplay(_t("File is too big. File size cannot exceed 25MB"));
            this._fileReset();
            this.state.preview.show = false;
            return;
        }
        this.file.name = file.name;
        this.file.type = "text/html";
        const dataURL = await getDataURLFromFile(file);
        this.file.data = dataURL.split(",", 2)[1];
        this.state.form.slideImage = "/website_slides/static/src/img/document.png";
        this.state.preview.show = true;
        if (!preventOnchange && this.state.form.slideName === "") {
            const input = file.name;
            this.state.form.slideName = input.substr(0, input.lastIndexOf(".")) || input;
        }
    },

    async _formValidateGetValues(forcePublished) {
        const values = await super._formValidateGetValues(forcePublished);
        if (this.file.type === "text/html") {
            // Core only sets binary_content for pdf/image; add it for HTML and
            // keep it in the 'document' category (server sets slide_type='html').
            Object.assign(values, {
                slide_category: "document",
                binary_content: this.file.data,
            });
        }
        return values;
    },
});
