package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"strings"

	"github.com/gauravarora90/smart-summarizer/go-api/handlers"
	"github.com/gorilla/mux"
)

var llmServiceURL string

func main() {
    llmServiceURL = os.Getenv("LLM_SERVICE_URL")
	if llmServiceURL == "" {
		llmServiceURL = "http://llm-service:8000"
	}
    r := mux.NewRouter()
    r.HandleFunc("/health", handlers.Health).Methods("GET")
    r.HandleFunc("/summarize", handlers.SummarizeHandler).Methods("POST")
    log.Println("Go API listening at :8080")
    http.ListenAndServe(":8080", r)
}

func summarizeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	ct := r.Header.Get("Content-Type")
	if strings.HasPrefix(ct, "multipart/form-data") {
		// parse multipart (file)
		err := r.ParseMultipartForm(100 << 20) // 100 MB limit (adjust)
		if err != nil {
			http.Error(w, "could not parse multipart: "+err.Error(), http.StatusBadRequest)
			return
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			http.Error(w, "file is required in form field 'file': "+err.Error(), http.StatusBadRequest)
			return
		}
		defer file.Close()

		var b bytes.Buffer
		wr := multipart.NewWriter(&b)
		fw, _ := wr.CreateFormFile("file", header.Filename)
		_, err = io.Copy(fw, file)
		if err != nil {
			http.Error(w, "error copying file: "+err.Error(), http.StatusInternalServerError)
			return
		}
		// add any extra fields if desired:
		// wr.WriteField("foo", "bar")
		wr.Close()

		req, _ := http.NewRequest("POST", llmServiceURL+"/v1/summarize-file", &b)
		req.Header.Set("Content-Type", wr.FormDataContentType())

		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			http.Error(w, "error contacting llm service: "+err.Error(), http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()
		copyResponse(w, resp)
		return
	}

	// assume JSON text
	var body map[string]interface{}
	err := json.NewDecoder(r.Body).Decode(&body)
	if err != nil {
		http.Error(w, "invalid json body: "+err.Error(), http.StatusBadRequest)
		return
	}
	textBytes, _ := json.Marshal(body)
	resp, err := http.Post(llmServiceURL+"/v1/summarize", "application/json", bytes.NewReader(textBytes))
	if err != nil {
		http.Error(w, "error contacting llm service: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	copyResponse(w, resp)
}

func copyResponse(w http.ResponseWriter, resp *http.Response) {
	// copy headers
	for k, v := range resp.Header {
		for _, val := range v {
			w.Header().Add(k, val)
		}
	}
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}